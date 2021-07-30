# Copyright 2013 Josh Durgin
# Copyright 2013 Red Hat, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import datetime

import fixtures
import mock
from oslo_serialization import jsonutils
from oslo_utils import encodeutils
from oslo_utils.fixture import uuidsentinel as uuids
import six
from six.moves import urllib
import webob
from webob import exc

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack.compute import assisted_volume_snapshots \
        as assisted_snaps_v21
from nova.api.openstack.compute import volumes as volumes_v21
from nova.compute import api as compute_api
from nova.compute import flavors
from nova.compute import task_states
from nova.compute import vm_states
import nova.conf
from nova import context
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_instance
from nova.volume import cinder


CONF = nova.conf.CONF

# This is the server ID.
FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
# This is the old volume ID (to swap from).
FAKE_UUID_A = '00000000-aaaa-aaaa-aaaa-000000000000'
# This is the new volume ID (to swap to).
FAKE_UUID_B = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
# This is a volume that is not found.
FAKE_UUID_C = 'cccccccc-cccc-cccc-cccc-cccccccccccc'

IMAGE_UUID = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'


def fake_get_instance(self, context, instance_id, expected_attrs=None,
                      cell_down_support=False):
    return fake_instance.fake_instance_obj(context, **{'uuid': instance_id})


def fake_get_volume(self, context, id):
    if id == FAKE_UUID_A:
        status = 'in-use'
        attach_status = 'attached'
    elif id == FAKE_UUID_B:
        status = 'available'
        attach_status = 'detached'
    else:
        raise exception.VolumeNotFound(volume_id=id)
    return {'id': id, 'status': status, 'attach_status': attach_status}


def fake_create_snapshot(self, context, volume, name, description):
    return {'id': 123,
            'volume_id': 'fakeVolId',
            'status': 'available',
            'volume_size': 123,
            'created_at': '2013-01-01 00:00:01',
            'display_name': 'myVolumeName',
            'display_description': 'myVolumeDescription'}


def fake_delete_snapshot(self, context, snapshot_id):
    pass


def fake_compute_volume_snapshot_delete(self, context, volume_id, snapshot_id,
                                        delete_info):
    pass


@classmethod
def fake_bdm_get_by_volume_and_instance(cls, ctxt, volume_id, instance_uuid):
    if volume_id != FAKE_UUID_A:
        raise exception.VolumeBDMNotFound(volume_id=volume_id)
    db_bdm = fake_block_device.FakeDbBlockDeviceDict(
        {'id': 1,
         'instance_uuid': instance_uuid,
         'device_name': '/dev/fake0',
         'delete_on_termination': 'False',
         'source_type': 'volume',
         'destination_type': 'volume',
         'snapshot_id': None,
         'volume_id': FAKE_UUID_A,
         'volume_size': 1})
    return objects.BlockDeviceMapping._from_db_object(
        ctxt, objects.BlockDeviceMapping(), db_bdm)


class BootFromVolumeTest(test.TestCase):

    def setUp(self):
        super(BootFromVolumeTest, self).setUp()
        self.stub_out('nova.compute.api.API.create',
                      self._get_fake_compute_api_create())
        fakes.stub_out_nw_api(self)
        self._block_device_mapping_seen = None
        self._legacy_bdm_seen = True

    def _get_fake_compute_api_create(self):
        def _fake_compute_api_create(cls, context, instance_type,
                                    image_href, **kwargs):
            self._block_device_mapping_seen = kwargs.get(
                'block_device_mapping')
            self._legacy_bdm_seen = kwargs.get('legacy_bdm')

            inst_type = flavors.get_flavor_by_flavor_id(2)
            resv_id = None
            return ([{'id': 1,
                      'display_name': 'test_server',
                      'uuid': FAKE_UUID,
                      'instance_type': inst_type,
                      'access_ip_v4': '1.2.3.4',
                      'access_ip_v6': 'fead::1234',
                      'image_ref': IMAGE_UUID,
                      'user_id': 'fake',
                      'project_id': 'fake',
                      'created_at': datetime.datetime(2010, 10, 10, 12, 0, 0),
                      'updated_at': datetime.datetime(2010, 11, 11, 11, 0, 0),
                      'progress': 0,
                      'fixed_ips': []
                      }], resv_id)
        return _fake_compute_api_create

    def test_create_root_volume(self):
        body = dict(server=dict(
                name='test_server', imageRef=IMAGE_UUID,
                flavorRef=2, min_count=1, max_count=1,
                block_device_mapping=[dict(
                        volume_id='ca9fe3f5-cede-43cb-8050-1672acabe348',
                        device_name='/dev/vda',
                        delete_on_termination=False,
                        )]
                ))
        req = fakes.HTTPRequest.blank('/v2/fake/os-volumes_boot')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes(body)
        req.headers['content-type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app_v21())
        self.assertEqual(202, res.status_int)
        server = jsonutils.loads(res.body)['server']
        self.assertEqual(FAKE_UUID, server['id'])
        self.assertEqual(CONF.password_length, len(server['adminPass']))
        self.assertEqual(1, len(self._block_device_mapping_seen))
        self.assertTrue(self._legacy_bdm_seen)
        self.assertEqual('ca9fe3f5-cede-43cb-8050-1672acabe348',
                         self._block_device_mapping_seen[0]['volume_id'])
        self.assertEqual('/dev/vda',
                         self._block_device_mapping_seen[0]['device_name'])

    def test_create_root_volume_bdm_v2(self):
        body = dict(server=dict(
                name='test_server', imageRef=IMAGE_UUID,
                flavorRef=2, min_count=1, max_count=1,
                block_device_mapping_v2=[dict(
                        source_type='volume',
                        uuid='1',
                        device_name='/dev/vda',
                        boot_index=0,
                        delete_on_termination=False,
                        )]
                ))
        req = fakes.HTTPRequest.blank('/v2/fake/os-volumes_boot')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes(body)
        req.headers['content-type'] = 'application/json'
        res = req.get_response(fakes.wsgi_app_v21())
        self.assertEqual(202, res.status_int)
        server = jsonutils.loads(res.body)['server']
        self.assertEqual(FAKE_UUID, server['id'])
        self.assertEqual(CONF.password_length, len(server['adminPass']))
        self.assertEqual(1, len(self._block_device_mapping_seen))
        self.assertFalse(self._legacy_bdm_seen)
        self.assertEqual('1', self._block_device_mapping_seen[0]['volume_id'])
        self.assertEqual(0, self._block_device_mapping_seen[0]['boot_index'])
        self.assertEqual('/dev/vda',
                         self._block_device_mapping_seen[0]['device_name'])


class VolumeApiTestV21(test.NoDBTestCase):
    url_prefix = '/v2/fake'

    def setUp(self):
        super(VolumeApiTestV21, self).setUp()
        fakes.stub_out_networking(self)

        self.stub_out('nova.volume.cinder.API.delete',
                      lambda self, context, volume_id: None)
        self.stub_out('nova.volume.cinder.API.get', fakes.stub_volume_get)
        self.stub_out('nova.volume.cinder.API.get_all',
                      fakes.stub_volume_get_all)

        self.context = context.get_admin_context()

    @property
    def app(self):
        return fakes.wsgi_app_v21()

    def test_volume_create(self):
        self.stub_out('nova.volume.cinder.API.create',
                      fakes.stub_volume_create)

        vol = {"size": 100,
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "zone1:host1"}
        body = {"volume": vol}
        req = fakes.HTTPRequest.blank(self.url_prefix + '/os-volumes')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes(body)
        req.headers['content-type'] = 'application/json'
        resp = req.get_response(self.app)

        self.assertEqual(200, resp.status_int)

        resp_dict = jsonutils.loads(resp.body)
        self.assertIn('volume', resp_dict)
        self.assertEqual(vol['size'], resp_dict['volume']['size'])
        self.assertEqual(vol['display_name'],
                         resp_dict['volume']['displayName'])
        self.assertEqual(vol['display_description'],
                         resp_dict['volume']['displayDescription'])
        self.assertEqual(vol['availability_zone'],
                         resp_dict['volume']['availabilityZone'])

    @mock.patch.object(cinder.API, 'create')
    def _test_volume_translate_exception(self, cinder_exc, api_exc,
                                         mock_create):
        """Tests that cinder exceptions are correctly translated"""
        mock_create.side_effect = cinder_exc

        vol = {"size": '10',
               "display_name": "Volume Test Name",
               "display_description": "Volume Test Desc",
               "availability_zone": "zone1:host1"}
        body = {"volume": vol}

        req = fakes.HTTPRequest.blank(self.url_prefix + '/os-volumes')
        self.assertRaises(api_exc,
                          volumes_v21.VolumeController().create, req,
                          body=body)
        mock_create.assert_called_once_with(
            req.environ['nova.context'], '10', 'Volume Test Name',
            'Volume Test Desc', availability_zone='zone1:host1',
            metadata=None, snapshot=None, volume_type=None)

    @mock.patch.object(cinder.API, 'get_snapshot')
    @mock.patch.object(cinder.API, 'create')
    def test_volume_create_bad_snapshot_id(self, mock_create, mock_get):
        vol = {"snapshot_id": '1', "size": 10}
        body = {"volume": vol}
        mock_get.side_effect = exception.SnapshotNotFound(snapshot_id='1')

        req = fakes.HTTPRequest.blank(self.url_prefix + '/os-volumes')
        self.assertRaises(webob.exc.HTTPNotFound,
                          volumes_v21.VolumeController().create, req,
                          body=body)

    def test_volume_create_bad_input(self):
        self._test_volume_translate_exception(
            exception.InvalidInput(reason='fake'), webob.exc.HTTPBadRequest)

    def test_volume_create_bad_quota(self):
        self._test_volume_translate_exception(
            exception.OverQuota(overs='fake'), webob.exc.HTTPForbidden)

    def test_volume_index(self):
        req = fakes.HTTPRequest.blank(self.url_prefix + '/os-volumes')
        resp = req.get_response(self.app)
        self.assertEqual(200, resp.status_int)

    def test_volume_detail(self):
        req = fakes.HTTPRequest.blank(self.url_prefix + '/os-volumes/detail')
        resp = req.get_response(self.app)
        self.assertEqual(200, resp.status_int)

    def test_volume_show(self):
        req = fakes.HTTPRequest.blank(self.url_prefix + '/os-volumes/123')
        resp = req.get_response(self.app)
        self.assertEqual(200, resp.status_int)

    @mock.patch.object(cinder.API, 'get',
                       side_effect=exception.VolumeNotFound(
                           volume_id=uuids.volume))
    def test_volume_show_no_volume(self, mock_get):
        req = fakes.HTTPRequest.blank('%s/os-volumes/%s' % (self.url_prefix,
                                                            uuids.volume))
        resp = req.get_response(self.app)
        self.assertEqual(404, resp.status_int)
        self.assertIn('Volume %s could not be found.' % uuids.volume,
                      encodeutils.safe_decode(resp.body))
        mock_get.assert_called_once_with(req.environ['nova.context'],
                                         uuids.volume)

    def test_volume_delete(self):
        req = fakes.HTTPRequest.blank(self.url_prefix + '/os-volumes/123')
        req.method = 'DELETE'
        resp = req.get_response(self.app)
        self.assertEqual(202, resp.status_int)

    @mock.patch.object(cinder.API, 'delete',
                       side_effect=exception.VolumeNotFound(
                           volume_id=uuids.volume))
    def test_volume_delete_no_volume(self, mock_delete):
        req = fakes.HTTPRequest.blank('%s/os-volumes/%s' % (self.url_prefix,
                                                            uuids.volume))
        req.method = 'DELETE'
        resp = req.get_response(self.app)
        self.assertEqual(404, resp.status_int)
        self.assertIn('Volume %s could not be found.' % uuids.volume,
                      encodeutils.safe_decode(resp.body))
        mock_delete.assert_called_once_with(req.environ['nova.context'],
                                            uuids.volume)

    def _test_list_with_invalid_filter(self, url):
        prefix = '/os-volumes'
        req = fakes.HTTPRequest.blank(prefix + url)
        self.assertRaises(exception.ValidationError,
                          volumes_v21.VolumeController().index,
                          req)

    def test_list_with_invalid_non_int_limit(self):
        self._test_list_with_invalid_filter('?limit=-9')

    def test_list_with_invalid_string_limit(self):
        self._test_list_with_invalid_filter('?limit=abc')

    def test_list_duplicate_query_with_invalid_string_limit(self):
        self._test_list_with_invalid_filter(
            '?limit=1&limit=abc')

    def test_detail_list_with_invalid_non_int_limit(self):
        self._test_list_with_invalid_filter('/detail?limit=-9')

    def test_detail_list_with_invalid_string_limit(self):
        self._test_list_with_invalid_filter('/detail?limit=abc')

    def test_detail_list_duplicate_query_with_invalid_string_limit(self):
        self._test_list_with_invalid_filter(
            '/detail?limit=1&limit=abc')

    def test_list_with_invalid_non_int_offset(self):
        self._test_list_with_invalid_filter('?offset=-9')

    def test_list_with_invalid_string_offset(self):
        self._test_list_with_invalid_filter('?offset=abc')

    def test_list_duplicate_query_with_invalid_string_offset(self):
        self._test_list_with_invalid_filter(
            '?offset=1&offset=abc')

    def test_detail_list_with_invalid_non_int_offset(self):
        self._test_list_with_invalid_filter('/detail?offset=-9')

    def test_detail_list_with_invalid_string_offset(self):
        self._test_list_with_invalid_filter('/detail?offset=abc')

    def test_detail_list_duplicate_query_with_invalid_string_offset(self):
        self._test_list_with_invalid_filter(
            '/detail?offset=1&offset=abc')

    def _test_list_duplicate_query_parameters_validation(self, url):
        params = {
            'limit': 1,
            'offset': 1
        }
        for param, value in params.items():
            req = fakes.HTTPRequest.blank(
                self.url_prefix + url + '?%s=%s&%s=%s' %
                (param, value, param, value))
            resp = req.get_response(self.app)
            self.assertEqual(200, resp.status_int)

    def test_list_duplicate_query_parameters_validation(self):
        self._test_list_duplicate_query_parameters_validation('/os-volumes')

    def test_detail_list_duplicate_query_parameters_validation(self):
        self._test_list_duplicate_query_parameters_validation(
            '/os-volumes/detail')

    def test_list_with_additional_filter(self):
        req = fakes.HTTPRequest.blank(self.url_prefix +
            '/os-volumes?limit=1&offset=1&additional=something')
        resp = req.get_response(self.app)
        self.assertEqual(200, resp.status_int)

    def test_detail_list_with_additional_filter(self):
        req = fakes.HTTPRequest.blank(self.url_prefix +
            '/os-volumes/detail?limit=1&offset=1&additional=something')
        resp = req.get_response(self.app)
        self.assertEqual(200, resp.status_int)


class VolumeAttachTestsV21(test.NoDBTestCase):
    validation_error = exception.ValidationError
    microversion = '2.1'
    _prefix = '/servers/id/os-volume_attachments'

    def setUp(self):
        super(VolumeAttachTestsV21, self).setUp()
        self.stub_out('nova.objects.BlockDeviceMapping'
                      '.get_by_volume_and_instance',
                      fake_bdm_get_by_volume_and_instance)
        self.stub_out('nova.compute.api.API.get', fake_get_instance)
        self.stub_out('nova.volume.cinder.API.get', fake_get_volume)
        self.context = context.get_admin_context()
        self.expected_show = {'volumeAttachment':
            {'device': '/dev/fake0',
             'serverId': FAKE_UUID,
             'id': FAKE_UUID_A,
             'volumeId': FAKE_UUID_A
            }}
        self.attachments = volumes_v21.VolumeAttachmentController()

        self.req = self._build_request('/uuid')
        self.req.body = jsonutils.dump_as_bytes({})
        self.req.headers['content-type'] = 'application/json'
        self.req.environ['nova.context'] = self.context

    def _build_request(self, url=''):
        return fakes.HTTPRequest.blank(
            self._prefix + url, version=self.microversion)

    def test_show(self):
        result = self.attachments.show(self.req, FAKE_UUID, FAKE_UUID_A)
        self.assertEqual(self.expected_show, result)

    @mock.patch.object(compute_api.API, 'get',
        side_effect=exception.InstanceNotFound(instance_id=FAKE_UUID))
    def test_show_no_instance(self, mock_mr):
        self.assertRaises(exc.HTTPNotFound,
                          self.attachments.show,
                          self.req,
                          FAKE_UUID,
                          FAKE_UUID_A)

    @mock.patch.object(objects.BlockDeviceMapping,
                       'get_by_volume_and_instance',
                       side_effect=exception.VolumeBDMNotFound(
                           volume_id=FAKE_UUID_A))
    def test_show_no_bdms(self, mock_mr):
        self.assertRaises(exc.HTTPNotFound,
                          self.attachments.show,
                          self.req,
                          FAKE_UUID,
                          FAKE_UUID_A)

    def test_show_bdms_no_mountpoint(self):
        FAKE_UUID_NOTEXIST = '00000000-aaaa-aaaa-aaaa-aaaaaaaaaaaa'

        self.assertRaises(exc.HTTPNotFound,
                          self.attachments.show,
                          self.req,
                          FAKE_UUID,
                          FAKE_UUID_NOTEXIST)

    def test_detach(self):
        self.stub_out('nova.compute.api.API.detach_volume',
                      lambda self, context, instance, volume: None)
        inst = fake_instance.fake_instance_obj(self.context,
                                               **{'uuid': FAKE_UUID})
        with mock.patch.object(common, 'get_instance',
                               return_value=inst) as mock_get_instance:
            result = self.attachments.delete(self.req, FAKE_UUID, FAKE_UUID_A)
            # NOTE: on v2.1, http status code is set as wsgi_code of API
            # method instead of status_int in a response object.
            if isinstance(self.attachments,
                          volumes_v21.VolumeAttachmentController):
                status_int = self.attachments.delete.wsgi_code
            else:
                status_int = result.status_int
            self.assertEqual(202, status_int)
            mock_get_instance.assert_called_with(
                self.attachments.compute_api, self.context, FAKE_UUID,
                expected_attrs=['device_metadata'])

    @mock.patch.object(common, 'get_instance')
    def test_detach_vol_shelved_not_supported(self, mock_get_instance):
        inst = fake_instance.fake_instance_obj(self.context,
                                               **{'uuid': FAKE_UUID})
        inst.vm_state = vm_states.SHELVED
        mock_get_instance.return_value = inst
        req = fakes.HTTPRequest.blank(
                  '/v2/servers/id/os-volume_attachments/uuid', version='2.19')
        req.method = 'DELETE'
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context
        self.assertRaises(webob.exc.HTTPConflict,
                          self.attachments.delete,
                          req,
                          FAKE_UUID,
                          FAKE_UUID_A)

    @mock.patch.object(compute_api.API, 'detach_volume')
    @mock.patch.object(common, 'get_instance')
    def test_detach_vol_shelved_supported(self,
                                          mock_get_instance,
                                          mock_detach):
        inst = fake_instance.fake_instance_obj(self.context,
                                               **{'uuid': FAKE_UUID})
        inst.vm_state = vm_states.SHELVED
        mock_get_instance.return_value = inst
        req = fakes.HTTPRequest.blank(
                  '/v2/servers/id/os-volume_attachments/uuid', version='2.20')
        req.method = 'DELETE'
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context
        self.attachments.delete(req, FAKE_UUID, FAKE_UUID_A)
        self.assertTrue(mock_detach.called)

    def test_detach_vol_not_found(self):
        self.stub_out('nova.compute.api.API.detach_volume',
                      lambda self, context, instance, volume: None)

        self.assertRaises(exc.HTTPNotFound,
                          self.attachments.delete,
                          self.req,
                          FAKE_UUID,
                          FAKE_UUID_C)

    @mock.patch('nova.objects.BlockDeviceMapping.is_root',
                 new_callable=mock.PropertyMock)
    def test_detach_vol_root(self, mock_isroot):
        mock_isroot.return_value = True
        self.assertRaises(exc.HTTPBadRequest,
                          self.attachments.delete,
                          self.req,
                          FAKE_UUID,
                          FAKE_UUID_A)

    @mock.patch.object(compute_api.API, 'detach_volume')
    def test_detach_volume_from_locked_server(self, mock_detach_volume):
        mock_detach_volume.side_effect = exception.InstanceIsLocked(
            instance_uuid=FAKE_UUID)
        self.assertRaises(webob.exc.HTTPConflict, self.attachments.delete,
                          self.req, FAKE_UUID, FAKE_UUID_A)
        mock_detach_volume.assert_called_once_with(
            self.req.environ['nova.context'],
            test.MatchType(objects.Instance),
            {'attach_status': 'attached',
             'status': 'in-use',
             'id': FAKE_UUID_A})

    def test_attach_volume(self):
        self.stub_out('nova.compute.api.API.attach_volume',
                      lambda self, context, instance, volume_id,
                              device, tag=None,
                              supports_multiattach=False,
                              delete_on_termination=False: None)
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                    'device': '/dev/fake'}}
        result = self.attachments.create(self.req, FAKE_UUID, body=body)
        self.assertEqual('00000000-aaaa-aaaa-aaaa-000000000000',
                         result['volumeAttachment']['id'])

    @mock.patch.object(compute_api.API, 'attach_volume',
                       side_effect=exception.VolumeTaggedAttachNotSupported())
    def test_tagged_volume_attach_not_supported(self, mock_attach_volume):
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                     'device': '/dev/fake'}}
        self.assertRaises(webob.exc.HTTPBadRequest, self.attachments.create,
                          self.req, FAKE_UUID, body=body)

    @mock.patch.object(common, 'get_instance')
    def test_attach_vol_shelved_not_supported(self, mock_get_instance):
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                    'device': '/dev/fake'}}

        inst = fake_instance.fake_instance_obj(self.context,
                                               **{'uuid': FAKE_UUID})
        inst.vm_state = vm_states.SHELVED
        mock_get_instance.return_value = inst
        self.assertRaises(webob.exc.HTTPConflict,
                          self.attachments.create,
                          self.req,
                          FAKE_UUID,
                          body=body)

    @mock.patch.object(compute_api.API, 'attach_volume',
                       return_value='/dev/myfake')
    @mock.patch.object(common, 'get_instance')
    def test_attach_vol_shelved_supported(self,
                                          mock_get_instance,
                                          mock_attach):
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                    'device': '/dev/fake'}}

        inst = fake_instance.fake_instance_obj(self.context,
                                               **{'uuid': FAKE_UUID})
        inst.vm_state = vm_states.SHELVED
        mock_get_instance.return_value = inst
        req = fakes.HTTPRequest.blank('/v2/servers/id/os-volume_attachments',
                                      version='2.20')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context
        result = self.attachments.create(req, FAKE_UUID, body=body)
        self.assertEqual('00000000-aaaa-aaaa-aaaa-000000000000',
                         result['volumeAttachment']['id'])
        self.assertEqual('/dev/myfake', result['volumeAttachment']['device'])

    @mock.patch.object(compute_api.API, 'attach_volume',
                       return_value='/dev/myfake')
    def test_attach_volume_with_auto_device(self, mock_attach):
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                    'device': None}}
        result = self.attachments.create(self.req, FAKE_UUID, body=body)
        self.assertEqual('00000000-aaaa-aaaa-aaaa-000000000000',
                         result['volumeAttachment']['id'])
        self.assertEqual('/dev/myfake', result['volumeAttachment']['device'])

    @mock.patch.object(compute_api.API, 'attach_volume',
                       side_effect=exception.InstanceIsLocked(
                           instance_uuid=uuids.instance))
    def test_attach_volume_to_locked_server(self, mock_attach_volume):
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                    'device': '/dev/fake'}}
        self.assertRaises(webob.exc.HTTPConflict, self.attachments.create,
                          self.req, FAKE_UUID, body=body)
        supports_multiattach = api_version_request.is_supported(
            self.req, '2.60')
        mock_attach_volume.assert_called_once_with(
            self.req.environ['nova.context'],
            test.MatchType(objects.Instance), FAKE_UUID_A, '/dev/fake',
            supports_multiattach=supports_multiattach,
            delete_on_termination=False, tag=None)

    def test_attach_volume_bad_id(self):
        self.stub_out('nova.compute.api.API.attach_volume',
                      lambda self, context, instance, volume_id, device,
                             tag=None, supports_multiattach=False: None)

        body = {
            'volumeAttachment': {
                'device': None,
                'volumeId': 'TESTVOLUME',
            }
        }
        self.assertRaises(self.validation_error, self.attachments.create,
                          self.req, FAKE_UUID, body=body)

    @mock.patch.object(compute_api.API, 'attach_volume',
                       side_effect=exception.DevicePathInUse(path='/dev/sda'))
    def test_attach_volume_device_in_use(self, mock_attach):

        body = {
            'volumeAttachment': {
                'device': '/dev/sda',
                'volumeId': FAKE_UUID_A,
            }
        }

        self.assertRaises(webob.exc.HTTPConflict, self.attachments.create,
                          self.req, FAKE_UUID, body=body)

    def test_attach_volume_without_volumeId(self):
        self.stub_out('nova.compute.api.API.attach_volume',
                      lambda self, context, instance, volume_id, device,
                             tag=None, supports_multiattach=False: None)

        body = {
            'volumeAttachment': {
                'device': None
            }
        }

        self.assertRaises(self.validation_error, self.attachments.create,
                          self.req, FAKE_UUID, body=body)

    def test_attach_volume_with_extra_arg(self):
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                    'device': '/dev/fake',
                                    'extra': 'extra_arg'}}

        self.assertRaises(self.validation_error, self.attachments.create,
                          self.req, FAKE_UUID, body=body)

    @mock.patch.object(compute_api.API, 'attach_volume')
    def test_attach_volume_with_invalid_input(self, mock_attach):
        mock_attach.side_effect = exception.InvalidInput(
            reason='Invalid volume')

        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                     'device': '/dev/fake'}}

        req = self._build_request()
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes({})
        req.headers['content-type'] = 'application/json'
        req.environ['nova.context'] = self.context

        self.assertRaises(exc.HTTPBadRequest, self.attachments.create,
                          req, FAKE_UUID, body=body)

    def _test_swap(self, attachments, uuid=FAKE_UUID_A, body=None):
        body = body or {'volumeAttachment': {'volumeId': FAKE_UUID_B}}
        return attachments.update(self.req, uuids.instance, uuid, body=body)

    @mock.patch.object(compute_api.API, 'swap_volume',
                       side_effect=exception.InstanceIsLocked(
                           instance_uuid=uuids.instance))
    def test_swap_volume_for_locked_server(self, mock_swap_volume):
        self.assertRaises(webob.exc.HTTPConflict, self._test_swap,
                          self.attachments)
        mock_swap_volume.assert_called_once_with(
            self.req.environ['nova.context'], test.MatchType(objects.Instance),
            {'attach_status': 'attached',
             'status': 'in-use',
             'id': FAKE_UUID_A},
            {'attach_status': 'detached',
             'status': 'available',
             'id': FAKE_UUID_B})

    @mock.patch.object(compute_api.API, 'swap_volume')
    def test_swap_volume(self, mock_swap_volume):
        result = self._test_swap(self.attachments)
        # NOTE: on v2.1, http status code is set as wsgi_code of API
        # method instead of status_int in a response object.
        if isinstance(self.attachments,
                      volumes_v21.VolumeAttachmentController):
            status_int = self.attachments.update.wsgi_code
        else:
            status_int = result.status_int
        self.assertEqual(202, status_int)
        mock_swap_volume.assert_called_once_with(
            self.req.environ['nova.context'], test.MatchType(objects.Instance),
            {'attach_status': 'attached',
             'status': 'in-use',
             'id': FAKE_UUID_A},
            {'attach_status': 'detached',
             'status': 'available',
             'id': FAKE_UUID_B})

    def test_swap_volume_with_nonexistent_uri(self):
        self.assertRaises(exc.HTTPNotFound, self._test_swap,
                          self.attachments, uuid=FAKE_UUID_C)

    @mock.patch.object(cinder.API, 'get')
    def test_swap_volume_with_nonexistent_dest_in_body(self, mock_get):
        mock_get.side_effect = [
            None, exception.VolumeNotFound(volume_id=FAKE_UUID_C)]
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_C}}
        self.assertRaises(exc.HTTPBadRequest, self._test_swap,
                          self.attachments, body=body)
        mock_get.assert_has_calls([
            mock.call(self.req.environ['nova.context'], FAKE_UUID_A),
            mock.call(self.req.environ['nova.context'], FAKE_UUID_C)])

    def test_swap_volume_without_volumeId(self):
        body = {'volumeAttachment': {'device': '/dev/fake'}}
        self.assertRaises(self.validation_error,
                          self._test_swap,
                          self.attachments,
                          body=body)

    def test_swap_volume_with_extra_arg(self):
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                    'device': '/dev/fake'}}

        self.assertRaises(self.validation_error,
                          self._test_swap,
                          self.attachments,
                          body=body)

    @mock.patch.object(compute_api.API, 'swap_volume',
                       side_effect=exception.VolumeBDMNotFound(
                           volume_id=FAKE_UUID_B))
    def test_swap_volume_for_bdm_not_found(self, mock_swap_volume):
        self.assertRaises(webob.exc.HTTPNotFound, self._test_swap,
                          self.attachments)
        mock_swap_volume.assert_called_once_with(
            self.req.environ['nova.context'], test.MatchType(objects.Instance),
            {'attach_status': 'attached',
             'status': 'in-use',
             'id': FAKE_UUID_A},
            {'attach_status': 'detached',
             'status': 'available',
             'id': FAKE_UUID_B})

    def _test_list_with_invalid_filter(self, url):
        req = self._build_request(url)
        self.assertRaises(exception.ValidationError,
                          self.attachments.index,
                          req,
                          FAKE_UUID)

    def test_list_with_invalid_non_int_limit(self):
        self._test_list_with_invalid_filter('?limit=-9')

    def test_list_with_invalid_string_limit(self):
        self._test_list_with_invalid_filter('?limit=abc')

    def test_list_duplicate_query_with_invalid_string_limit(self):
        self._test_list_with_invalid_filter(
            '?limit=1&limit=abc')

    def test_list_with_invalid_non_int_offset(self):
        self._test_list_with_invalid_filter('?offset=-9')

    def test_list_with_invalid_string_offset(self):
        self._test_list_with_invalid_filter('?offset=abc')

    def test_list_duplicate_query_with_invalid_string_offset(self):
        self._test_list_with_invalid_filter(
            '?offset=1&offset=abc')

    @mock.patch.object(objects.BlockDeviceMappingList,
                       'get_by_instance_uuid')
    def test_list_duplicate_query_parameters_validation(self, mock_get):
        fake_bdms = objects.BlockDeviceMappingList()
        mock_get.return_value = fake_bdms
        params = {
            'limit': 1,
            'offset': 1
        }
        for param, value in params.items():
            req = self._build_request('?%s=%s&%s=%s' %
                (param, value, param, value))
            self.attachments.index(req, FAKE_UUID)

    @mock.patch.object(objects.BlockDeviceMappingList,
                       'get_by_instance_uuid')
    def test_list_with_additional_filter(self, mock_get):
        fake_bdms = objects.BlockDeviceMappingList()
        mock_get.return_value = fake_bdms
        req = self._build_request(
            '?limit=1&additional=something')
        self.attachments.index(req, FAKE_UUID)


class VolumeAttachTestsV249(test.NoDBTestCase):
    validation_error = exception.ValidationError

    def setUp(self):
        super(VolumeAttachTestsV249, self).setUp()
        self.attachments = volumes_v21.VolumeAttachmentController()
        self.req = fakes.HTTPRequest.blank(
                  '/v2/servers/id/os-volume_attachments/uuid',
                  version='2.49')

    def test_tagged_volume_attach_invalid_tag_comma(self):
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                     'device': '/dev/fake',
                                     'tag': ','}}
        self.assertRaises(exception.ValidationError, self.attachments.create,
                          self.req, FAKE_UUID, body=body)

    def test_tagged_volume_attach_invalid_tag_slash(self):
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                     'device': '/dev/fake',
                                     'tag': '/'}}
        self.assertRaises(exception.ValidationError, self.attachments.create,
                          self.req, FAKE_UUID, body=body)

    def test_tagged_volume_attach_invalid_tag_too_long(self):
        tag = ''.join(map(str, range(10, 41)))
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                     'device': '/dev/fake',
                                     'tag': tag}}
        self.assertRaises(exception.ValidationError, self.attachments.create,
                          self.req, FAKE_UUID, body=body)

    @mock.patch('nova.compute.api.API.attach_volume')
    @mock.patch('nova.compute.api.API.get', fake_get_instance)
    def test_tagged_volume_attach_valid_tag(self, _):
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                     'device': '/dev/fake',
                                     'tag': 'foo'}}
        self.attachments.create(self.req, FAKE_UUID, body=body)


class VolumeAttachTestsV260(test.NoDBTestCase):
    """Negative tests for attaching a multiattach volume with version 2.60."""
    def setUp(self):
        super(VolumeAttachTestsV260, self).setUp()
        self.controller = volumes_v21.VolumeAttachmentController()
        get_instance = mock.patch('nova.compute.api.API.get')
        get_instance.side_effect = fake_get_instance
        get_instance.start()
        self.addCleanup(get_instance.stop)

    def _post_attach(self, version=None):
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A}}
        req = fakes.HTTPRequestV21.blank(
            '/servers/%s/os-volume_attachments' % FAKE_UUID,
            version=version or '2.60')
        req.body = jsonutils.dump_as_bytes(body)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        return self.controller.create(req, FAKE_UUID, body=body)

    def test_attach_with_multiattach_fails_old_microversion(self):
        """Tests the case that the user tries to attach with a
        multiattach volume but before using microversion 2.60.
        """
        with mock.patch.object(
                self.controller.compute_api, 'attach_volume',
                side_effect=
                exception.MultiattachNotSupportedOldMicroversion) as attach:
            ex = self.assertRaises(webob.exc.HTTPBadRequest,
                                   self._post_attach, '2.59')
        create_kwargs = attach.call_args[1]
        self.assertFalse(create_kwargs['supports_multiattach'])
        self.assertIn('Multiattach volumes are only supported starting with '
                      'compute API version 2.60', six.text_type(ex))

    def test_attach_with_multiattach_fails_not_supported_by_driver(self):
        """Tests the case that the user tries to attach with a
        multiattach volume but the compute hosting the instance does
        not support multiattach volumes. This would come from
        reserve_block_device_name via RPC call to the compute service.
        """
        with mock.patch.object(
                self.controller.compute_api, 'attach_volume',
                side_effect=
                exception.MultiattachNotSupportedByVirtDriver(
                    volume_id=FAKE_UUID_A)) as attach:
            ex = self.assertRaises(webob.exc.HTTPConflict, self._post_attach)
        create_kwargs = attach.call_args[1]
        self.assertTrue(create_kwargs['supports_multiattach'])
        self.assertIn("has 'multiattach' set, which is not supported for "
                      "this instance", six.text_type(ex))

    def test_attach_with_multiattach_fails_for_shelved_offloaded_server(self):
        """Tests the case that the user tries to attach with a
        multiattach volume to a shelved offloaded server which is
        not supported.
        """
        with mock.patch.object(
                self.controller.compute_api, 'attach_volume',
                side_effect=
                exception.MultiattachToShelvedNotSupported) as attach:
            ex = self.assertRaises(webob.exc.HTTPBadRequest, self._post_attach)
        create_kwargs = attach.call_args[1]
        self.assertTrue(create_kwargs['supports_multiattach'])
        self.assertIn('Attaching multiattach volumes is not supported for '
                      'shelved-offloaded instances.', six.text_type(ex))


class VolumeAttachTestsV2_75(VolumeAttachTestsV21):
    microversion = '2.75'

    def setUp(self):
        super(VolumeAttachTestsV2_75, self).setUp()
        self.expected_show = {'volumeAttachment':
            {'device': '/dev/fake0',
             'serverId': FAKE_UUID,
             'id': FAKE_UUID_A,
             'volumeId': FAKE_UUID_A,
             'tag': None,
            }}

    @mock.patch.object(objects.BlockDeviceMappingList,
                       'get_by_instance_uuid')
    def test_list_with_additional_filter_old_version(self, mock_get):
        fake_bdms = objects.BlockDeviceMappingList()
        mock_get.return_value = fake_bdms
        req = fakes.HTTPRequest.blank(
            '/os-volumes?limit=1&offset=1&additional=something',
            version='2.74')
        self.attachments.index(req, FAKE_UUID)

    def test_list_with_additional_filter(self):
        req = self._build_request(
            '?limit=1&additional=something')
        self.assertRaises(self.validation_error, self.attachments.index,
                          req, FAKE_UUID)


class VolumeAttachTestsV279(VolumeAttachTestsV2_75):
    microversion = '2.79'

    def setUp(self):
        super(VolumeAttachTestsV279, self).setUp()
        self.controller = volumes_v21.VolumeAttachmentController()
        self.expected_show = {'volumeAttachment':
            {'device': '/dev/fake0',
             'serverId': FAKE_UUID,
             'id': FAKE_UUID_A,
             'volumeId': FAKE_UUID_A,
             'tag': None,
             'delete_on_termination': False
            }}

    def _get_req(self, body, microversion=None):
        req = fakes.HTTPRequest.blank(
            '/v2/servers/id/os-volume_attachments/uuid',
            version=microversion or self.microversion)
        req.body = jsonutils.dump_as_bytes(body)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        return req

    def test_create_volume_attach_pre_v279(self):
        """Tests the case that the user tries to attach a volume with
        delete_on_termination field, but before using microversion 2.79.
        """
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                     'delete_on_termination': False}}
        req = self._get_req(body, microversion='2.78')
        ex = self.assertRaises(exception.ValidationError,
                               self.controller.create,
                               req, FAKE_UUID, body=body)
        self.assertIn("Additional properties are not allowed",
                      six.text_type(ex))

    @mock.patch('nova.compute.api.API.attach_volume', return_value=None)
    def test_attach_volume_pre_v279(self, mock_attach_volume):
        """Before microversion 2.79, attach a volume will not contain
        'delete_on_termination' field in the response.
        """
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A}}
        req = self._get_req(body, microversion='2.78')
        result = self.attachments.create(req, FAKE_UUID, body=body)
        self.assertNotIn('delete_on_termination', result['volumeAttachment'])
        mock_attach_volume.assert_called_once_with(
            req.environ['nova.context'], test.MatchType(objects.Instance),
            FAKE_UUID_A, None, tag=None, supports_multiattach=True,
            delete_on_termination=False)

    @mock.patch('nova.compute.api.API.attach_volume', return_value=None)
    def test_attach_volume_with_delete_on_termination_default_value(
            self, mock_attach_volume):
        """Test attach a volume doesn't specify 'delete_on_termination' in
        the request, you will be get it's default value in the response.
        The delete_on_termination's default value is 'False'.
        """
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A}}
        req = self._get_req(body)
        result = self.attachments.create(req, FAKE_UUID, body=body)
        self.assertFalse(result['volumeAttachment']['delete_on_termination'])
        mock_attach_volume.assert_called_once_with(
            req.environ['nova.context'], test.MatchType(objects.Instance),
            FAKE_UUID_A, None, tag=None, supports_multiattach=True,
            delete_on_termination=False)

    def test_create_volume_attach_invalid_delete_on_termination_empty(self):
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                     'delete_on_termination': None}}
        req = self._get_req(body)
        ex = self.assertRaises(exception.ValidationError,
                               self.controller.create,
                               req, FAKE_UUID, body=body)
        self.assertIn("Invalid input for field/attribute "
                      "delete_on_termination.", six.text_type(ex))

    def test_create_volume_attach_invalid_delete_on_termination_value(self):
        """"Test the case that the user tries to set the delete_on_termination
        value not in the boolean or string-boolean check, the valid boolean
        value are:

        [True, 'True', 'TRUE', 'true', '1', 'ON', 'On', 'on', 'YES', 'Yes',
        'yes', False, 'False', 'FALSE', 'false', '0', 'OFF', 'Off', 'off',
        'NO', 'No', 'no']
        """
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                     'delete_on_termination': 'foo'}}
        req = self._get_req(body)
        ex = self.assertRaises(exception.ValidationError,
                               self.controller.create,
                               req, FAKE_UUID, body=body)
        self.assertIn("Invalid input for field/attribute "
                      "delete_on_termination.", six.text_type(ex))


class SwapVolumeMultiattachTestCase(test.NoDBTestCase):

    @mock.patch('nova.api.openstack.common.get_instance')
    @mock.patch('nova.volume.cinder.API.begin_detaching')
    @mock.patch('nova.volume.cinder.API.roll_detaching')
    def test_swap_multiattach_multiple_readonly_attachments_fails(
            self, mock_roll_detaching, mock_begin_detaching,
            mock_get_instance):
        """Tests that trying to swap from a multiattach volume with
        multiple read/write attachments will return an error.
        """

        def fake_volume_get(_context, volume_id):
            if volume_id == uuids.old_vol_id:
                return {
                    'id': volume_id,
                    'size': 1,
                    'multiattach': True,
                    'attachments': {
                        uuids.server1: {
                            'attachment_id': uuids.attachment_id1,
                            'mountpoint': '/dev/vdb'
                        },
                        uuids.server2: {
                            'attachment_id': uuids.attachment_id2,
                            'mountpoint': '/dev/vdb'
                        }
                    }
                }
            if volume_id == uuids.new_vol_id:
                return {
                    'id': volume_id,
                    'size': 1,
                    'attach_status': 'detached'
                }
            raise exception.VolumeNotFound(volume_id=volume_id)

        def fake_attachment_get(_context, attachment_id):
            return {'attach_mode': 'rw'}

        ctxt = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctxt, uuid=uuids.server1, vm_state=vm_states.ACTIVE,
            task_state=None, launched_at=datetime.datetime(2018, 6, 6))
        mock_get_instance.return_value = instance
        controller = volumes_v21.VolumeAttachmentController()
        with test.nested(
                mock.patch.object(controller.volume_api, 'get',
                                  side_effect=fake_volume_get),
                mock.patch.object(controller.compute_api.volume_api,
                                  'attachment_get',
                                  side_effect=fake_attachment_get)) as (
            mock_volume_get, mock_attachment_get
        ):
            req = fakes.HTTPRequest.blank(
                '/servers/%s/os-volume_attachments/%s' %
                (uuids.server1, uuids.old_vol_id))
            req.headers['content-type'] = 'application/json'
            req.environ['nova.context'] = ctxt
            body = {
                'volumeAttachment': {
                    'volumeId': uuids.new_vol_id
                }
            }
            ex = self.assertRaises(
                webob.exc.HTTPBadRequest, controller.update, req,
                uuids.server1, uuids.old_vol_id, body=body)
        self.assertIn('Swapping multi-attach volumes with more than one ',
                      six.text_type(ex))
        mock_attachment_get.assert_has_calls([
            mock.call(ctxt, uuids.attachment_id1),
            mock.call(ctxt, uuids.attachment_id2)], any_order=True)
        mock_roll_detaching.assert_called_once_with(ctxt, uuids.old_vol_id)


class CommonBadRequestTestCase(object):

    resource = None
    entity_name = None
    controller_cls = None
    kwargs = {}
    bad_request = exc.HTTPBadRequest

    """
    Tests of places we throw 400 Bad Request from
    """

    def setUp(self):
        super(CommonBadRequestTestCase, self).setUp()
        self.controller = self.controller_cls()

    def _bad_request_create(self, body):
        req = fakes.HTTPRequest.blank('/v2/fake/' + self.resource)
        req.method = 'POST'

        kwargs = self.kwargs.copy()
        kwargs['body'] = body
        self.assertRaises(self.bad_request,
                          self.controller.create, req, **kwargs)

    def test_create_no_body(self):
        self._bad_request_create(body=None)

    def test_create_missing_volume(self):
        body = {'foo': {'a': 'b'}}
        self._bad_request_create(body=body)

    def test_create_malformed_entity(self):
        body = {self.entity_name: 'string'}
        self._bad_request_create(body=body)


class BadRequestVolumeTestCaseV21(CommonBadRequestTestCase,
                                  test.NoDBTestCase):

    resource = 'os-volumes'
    entity_name = 'volume'
    controller_cls = volumes_v21.VolumeController
    bad_request = exception.ValidationError

    @mock.patch.object(cinder.API, 'delete',
        side_effect=exception.InvalidInput(reason='vol attach'))
    def test_delete_invalid_status_volume(self, mock_delete):
        req = fakes.HTTPRequest.blank('/v2.1/os-volumes')
        req.method = 'DELETE'
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.delete, req, FAKE_UUID)


class BadRequestSnapshotTestCaseV21(CommonBadRequestTestCase,
                                    test.NoDBTestCase):

    resource = 'os-snapshots'
    entity_name = 'snapshot'
    controller_cls = volumes_v21.SnapshotController
    bad_request = exception.ValidationError


class AssistedSnapshotCreateTestCaseV21(test.NoDBTestCase):
    assisted_snaps = assisted_snaps_v21
    bad_request = exception.ValidationError

    def setUp(self):
        super(AssistedSnapshotCreateTestCaseV21, self).setUp()

        self.controller = \
            self.assisted_snaps.AssistedVolumeSnapshotsController()

    @mock.patch.object(compute_api.API, 'volume_snapshot_create')
    def test_assisted_create(self, mock_volume_snapshot_create):
        req = fakes.HTTPRequest.blank('/v2/fake/os-assisted-volume-snapshots')
        expected_create_info = {'type': 'qcow2',
                                'new_file': 'new_file',
                                'snapshot_id': 'snapshot_id'}
        body = {'snapshot': {'volume_id': uuids.volume_to_snapshot,
                             'create_info': expected_create_info}}
        req.method = 'POST'
        self.controller.create(req, body=body)

        mock_volume_snapshot_create.assert_called_once_with(
            req.environ['nova.context'], uuids.volume_to_snapshot,
            expected_create_info)

    def test_assisted_create_missing_create_info(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-assisted-volume-snapshots')
        body = {'snapshot': {'volume_id': '1'}}
        req.method = 'POST'
        self.assertRaises(self.bad_request, self.controller.create,
                req, body=body)

    def test_assisted_create_with_unexpected_attr(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-assisted-volume-snapshots')
        body = {
            'snapshot': {
                'volume_id': '1',
                'create_info': {
                    'type': 'qcow2',
                    'new_file': 'new_file',
                    'snapshot_id': 'snapshot_id'
                }
            },
            'unexpected': 0,
        }
        req.method = 'POST'
        self.assertRaises(self.bad_request, self.controller.create,
                req, body=body)

    @mock.patch('nova.objects.BlockDeviceMapping.get_by_volume',
                side_effect=exception.VolumeBDMIsMultiAttach(volume_id='1'))
    def test_assisted_create_multiattach_fails(self, bdm_get_by_volume):
        req = fakes.HTTPRequest.blank('/v2/fake/os-assisted-volume-snapshots')
        body = {'snapshot':
                   {'volume_id': '1',
                    'create_info': {'type': 'qcow2',
                                    'new_file': 'new_file',
                                    'snapshot_id': 'snapshot_id'}}}
        req.method = 'POST'
        self.assertRaises(
            webob.exc.HTTPBadRequest, self.controller.create, req, body=body)

    def _test_assisted_create_instance_conflict(self, api_error):
        req = fakes.HTTPRequest.blank('/v2/fake/os-assisted-volume-snapshots')
        body = {'snapshot':
                   {'volume_id': '1',
                    'create_info': {'type': 'qcow2',
                                    'new_file': 'new_file',
                                    'snapshot_id': 'snapshot_id'}}}
        req.method = 'POST'
        with mock.patch.object(compute_api.API, 'volume_snapshot_create',
                               side_effect=api_error):
            self.assertRaises(
                webob.exc.HTTPBadRequest, self.controller.create,
                req, body=body)

    def test_assisted_create_instance_invalid_state(self):
        api_error = exception.InstanceInvalidState(
            instance_uuid=FAKE_UUID, attr='task_state',
            state=task_states.SHELVING_OFFLOADING,
            method='volume_snapshot_create')
        self._test_assisted_create_instance_conflict(api_error)

    def test_assisted_create_instance_not_ready(self):
        api_error = exception.InstanceNotReady(instance_id=FAKE_UUID)
        self._test_assisted_create_instance_conflict(api_error)


class AssistedSnapshotDeleteTestCaseV21(test.NoDBTestCase):
    assisted_snaps = assisted_snaps_v21
    microversion = '2.1'

    def _check_status(self, expected_status, res, controller_method):
        self.assertEqual(expected_status, controller_method.wsgi_code)

    def setUp(self):
        super(AssistedSnapshotDeleteTestCaseV21, self).setUp()

        self.controller = \
            self.assisted_snaps.AssistedVolumeSnapshotsController()
        self.mock_volume_snapshot_delete = self.useFixture(
            fixtures.MockPatchObject(compute_api.API,
                                     'volume_snapshot_delete')).mock

    def test_assisted_delete(self):
        params = {
            'delete_info': jsonutils.dumps({'volume_id': '1'}),
        }
        req = fakes.HTTPRequest.blank(
                '/v2/fake/os-assisted-volume-snapshots?%s' %
                urllib.parse.urlencode(params),
                version=self.microversion)
        req.method = 'DELETE'
        result = self.controller.delete(req, '5')
        self._check_status(204, result, self.controller.delete)

    def test_assisted_delete_missing_delete_info(self):
        req = fakes.HTTPRequest.blank('/v2/fake/os-assisted-volume-snapshots',
                                      version=self.microversion)
        req.method = 'DELETE'
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.delete,
                req, '5')

    def _test_assisted_delete_instance_conflict(self, api_error):
        # unset the stub on volume_snapshot_delete from setUp
        self.mock_volume_snapshot_delete.stop()
        params = {
            'delete_info': jsonutils.dumps({'volume_id': '1'}),
        }
        req = fakes.HTTPRequest.blank(
                '/v2/fake/os-assisted-volume-snapshots?%s' %
                urllib.parse.urlencode(params),
                version=self.microversion)
        req.method = 'DELETE'
        with mock.patch.object(compute_api.API, 'volume_snapshot_delete',
                               side_effect=api_error):
            self.assertRaises(
                webob.exc.HTTPBadRequest, self.controller.delete, req, '5')

    def test_assisted_delete_instance_invalid_state(self):
        api_error = exception.InstanceInvalidState(
            instance_uuid=FAKE_UUID, attr='task_state',
            state=task_states.UNSHELVING,
            method='volume_snapshot_delete')
        self._test_assisted_delete_instance_conflict(api_error)

    def test_assisted_delete_instance_not_ready(self):
        api_error = exception.InstanceNotReady(instance_id=FAKE_UUID)
        self._test_assisted_delete_instance_conflict(api_error)

    def test_delete_additional_query_parameters(self):
        params = {
            'delete_info': jsonutils.dumps({'volume_id': '1'}),
            'additional': 123
        }
        req = fakes.HTTPRequest.blank(
                '/v2/fake/os-assisted-volume-snapshots?%s' %
                urllib.parse.urlencode(params),
                version=self.microversion)
        req.method = 'DELETE'
        self.controller.delete(req, '5')

    def test_delete_duplicate_query_parameters_validation(self):
        params = {
            'delete_info': jsonutils.dumps({'volume_id': '1'}),
            'delete_info': jsonutils.dumps({'volume_id': '2'})
        }
        req = fakes.HTTPRequest.blank(
                '/v2/fake/os-assisted-volume-snapshots?%s' %
                urllib.parse.urlencode(params),
                version=self.microversion)
        req.method = 'DELETE'
        self.controller.delete(req, '5')

    def test_assisted_delete_missing_volume_id(self):
        params = {
            'delete_info': jsonutils.dumps({'something_else': '1'}),
        }
        req = fakes.HTTPRequest.blank(
                '/v2/fake/os-assisted-volume-snapshots?%s' %
                urllib.parse.urlencode(params),
                version=self.microversion)

        req.method = 'DELETE'
        ex = self.assertRaises(webob.exc.HTTPBadRequest,
                               self.controller.delete, req, '5')
        # This is the result of a KeyError but the only thing in the message
        # is the missing key.
        self.assertIn('volume_id', six.text_type(ex))


class AssistedSnapshotDeleteTestCaseV275(AssistedSnapshotDeleteTestCaseV21):
    assisted_snaps = assisted_snaps_v21
    microversion = '2.75'

    def test_delete_additional_query_parameters_old_version(self):
        params = {
            'delete_info': jsonutils.dumps({'volume_id': '1'}),
            'additional': 123
        }
        req = fakes.HTTPRequest.blank(
                '/v2/fake/os-assisted-volume-snapshots?%s' %
                urllib.parse.urlencode(params),
                version='2.74')
        self.controller.delete(req, 1)

    def test_delete_additional_query_parameters(self):
        req = fakes.HTTPRequest.blank(
                '/v2/fake/os-assisted-volume-snapshots?unknown=1',
                version=self.microversion)
        self.assertRaises(exception.ValidationError,
                          self.controller.delete, req, 1)


class TestAssistedVolumeSnapshotsPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(TestAssistedVolumeSnapshotsPolicyEnforcementV21, self).setUp()
        self.controller = (
            assisted_snaps_v21.AssistedVolumeSnapshotsController())
        self.req = fakes.HTTPRequest.blank('')

    def test_create_assisted_volumes_snapshots_policy_failed(self):
        rule_name = "os_compute_api:os-assisted-volume-snapshots:create"
        self.policy.set_rules({rule_name: "project:non_fake"})
        body = {'snapshot':
                   {'volume_id': '1',
                    'create_info': {'type': 'qcow2',
                                    'new_file': 'new_file',
                                    'snapshot_id': 'snapshot_id'}}}
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.create, self.req, body=body)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_delete_assisted_volumes_snapshots_policy_failed(self):
        rule_name = "os_compute_api:os-assisted-volume-snapshots:delete"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.delete, self.req, '5')

        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())


class TestVolumeAttachPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(TestVolumeAttachPolicyEnforcementV21, self).setUp()
        self.controller = volumes_v21.VolumeAttachmentController()
        self.req = fakes.HTTPRequest.blank('')

    def _common_policy_check(self, rules, rule_name, func, *arg, **kwarg):
        self.policy.set_rules(rules)
        exc = self.assertRaises(
             exception.PolicyNotAuthorized, func, *arg, **kwarg)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_index_volume_attach_policy_failed(self):
        rule_name = "os_compute_api:os-volumes-attachments:index"
        rules = {rule_name: "project:non_fake"}
        self._common_policy_check(rules, rule_name,
                                  self.controller.index, self.req, FAKE_UUID)

    def test_show_volume_attach_policy_failed(self):
        rule_name = "os_compute_api:os-volumes-attachments:show"
        rules = {rule_name: "project:non_fake"}
        self._common_policy_check(rules, rule_name, self.controller.show,
                                  self.req, FAKE_UUID, FAKE_UUID_A)

    def test_create_volume_attach_policy_failed(self):
        rule_name = "os_compute_api:os-volumes-attachments:create"
        rules = {rule_name: "project:non_fake"}
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_A,
                                     'device': '/dev/fake'}}
        self._common_policy_check(rules, rule_name, self.controller.create,
                                  self.req, FAKE_UUID, body=body)

    def test_update_volume_attach_policy_failed(self):
        rule_name = "os_compute_api:os-volumes-attachments:update"
        rules = {rule_name: "project:non_fake"}
        body = {'volumeAttachment': {'volumeId': FAKE_UUID_B}}
        self._common_policy_check(rules, rule_name, self.controller.update,
                                  self.req, FAKE_UUID, FAKE_UUID_A, body=body)

    def test_delete_volume_attach_policy_failed(self):
        rule_name = "os_compute_api:os-volumes-attachments:delete"
        rules = {rule_name: "project:non_fake"}
        self._common_policy_check(rules, rule_name, self.controller.delete,
                                  self.req, FAKE_UUID, FAKE_UUID_A)


class TestVolumesAPIDeprecation(test.NoDBTestCase):

    def setUp(self):
        super(TestVolumesAPIDeprecation, self).setUp()
        self.controller = volumes_v21.VolumeController()
        self.req = fakes.HTTPRequest.blank('', version='2.36')

    def test_all_apis_return_not_found(self):
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.show, self.req, fakes.FAKE_UUID)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.delete, self.req, fakes.FAKE_UUID)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.index, self.req)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.create, self.req, {})
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.detail, self.req)
