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

import mock
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids

from nova import exception
from nova import objects
from nova.tests.unit.objects import test_instance_numa
from nova.tests.unit.objects import test_objects


fake_instance_uuid = uuids.fake

fake_migration_context_obj = objects.MigrationContext()
fake_migration_context_obj.instance_uuid = fake_instance_uuid
fake_migration_context_obj.migration_id = 42
fake_migration_context_obj.new_numa_topology = (
    test_instance_numa.fake_obj_numa_topology.obj_clone())
fake_migration_context_obj.old_numa_topology = None
fake_migration_context_obj.new_pci_devices = objects.PciDeviceList()
fake_migration_context_obj.old_pci_devices = None
fake_migration_context_obj.new_pci_requests = (
    objects.InstancePCIRequests(requests=[
        objects.InstancePCIRequest(count=123, spec=[])]))
fake_migration_context_obj.old_pci_requests = None
fake_migration_context_obj.new_resources = objects.ResourceList()
fake_migration_context_obj.old_resources = None

fake_db_context = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': 0,
    'instance_uuid': fake_instance_uuid,
    'migration_context': jsonutils.dumps(
        fake_migration_context_obj.obj_to_primitive()),
    }


def get_fake_migration_context_obj(ctxt):
    obj = fake_migration_context_obj.obj_clone()
    obj._context = ctxt
    return obj


def get_fake_migration_context_with_pci_devs(ctxt=None):
    obj = get_fake_migration_context_obj(ctxt)
    obj.old_pci_devices = objects.PciDeviceList(
        objects=[objects.PciDevice(vendor_id='1377',
                                   product_id='0047',
                                   address='0000:0a:00.1',
                                   compute_node_id=1,
                                   request_id=uuids.pcidev)])
    obj.new_pci_devices = objects.PciDeviceList(
        objects=[objects.PciDevice(vendor_id='1377',
                                   product_id='0047',
                                   address='0000:0b:00.1',
                                   compute_node_id=2,
                                   request_id=uuids.pcidev)])
    return obj


class _TestMigrationContext(object):

    def _test_get_by_instance_uuid(self, db_data):
        mig_context = objects.MigrationContext.get_by_instance_uuid(
            self.context, fake_db_context['instance_uuid'])
        if mig_context:
            self.assertEqual(fake_db_context['instance_uuid'],
                            mig_context.instance_uuid)
            expected_mig_context = db_data and db_data.get('migration_context')
            expected_mig_context = objects.MigrationContext.obj_from_db_obj(
                expected_mig_context)
            self.assertEqual(expected_mig_context.instance_uuid,
                             mig_context.instance_uuid)
            self.assertEqual(expected_mig_context.migration_id,
                             mig_context.migration_id)
            self.assertIsInstance(expected_mig_context.new_numa_topology,
                                  mig_context.new_numa_topology.__class__)
            self.assertIsInstance(expected_mig_context.old_numa_topology,
                                  mig_context.old_numa_topology.__class__)
            self.assertIsInstance(expected_mig_context.new_pci_devices,
                                  mig_context.new_pci_devices.__class__)
            self.assertIsInstance(expected_mig_context.old_pci_devices,
                                  mig_context.old_pci_devices.__class__)
            self.assertIsInstance(expected_mig_context.new_pci_requests,
                                  mig_context.new_pci_requests.__class__)
            self.assertIsInstance(expected_mig_context.old_pci_requests,
                                  mig_context.old_pci_requests.__class__)
            self.assertIsInstance(expected_mig_context. new_resources,
                                  mig_context.new_resources.__class__)
            self.assertIsInstance(expected_mig_context.old_resources,
                                  mig_context.old_resources.__class__)
        else:
            self.assertIsNone(mig_context)

    @mock.patch('nova.db.api.instance_extra_get_by_instance_uuid')
    def test_get_by_instance_uuid(self, mock_get):
        mock_get.return_value = fake_db_context
        self._test_get_by_instance_uuid(fake_db_context)

    @mock.patch('nova.db.api.instance_extra_get_by_instance_uuid')
    def test_get_by_instance_uuid_none(self, mock_get):
        db_context = fake_db_context.copy()
        db_context['migration_context'] = None
        mock_get.return_value = db_context
        self._test_get_by_instance_uuid(db_context)

    @mock.patch('nova.db.api.instance_extra_get_by_instance_uuid')
    def test_get_by_instance_uuid_missing(self, mock_get):
        mock_get.return_value = None
        self.assertRaises(
            exception.MigrationContextNotFound,
            objects.MigrationContext.get_by_instance_uuid,
            self.context, 'fake_uuid')


class TestMigrationContext(test_objects._LocalTest, _TestMigrationContext):

    def test_pci_mapping_for_migration(self):
        mig_ctx = get_fake_migration_context_with_pci_devs()
        pci_mapping = mig_ctx.get_pci_mapping_for_migration(False)
        self.assertDictEqual(
            {mig_ctx.old_pci_devices[0].address: mig_ctx.new_pci_devices[0]},
            pci_mapping)

    def test_pci_mapping_for_migration_revert(self):
        mig_ctx = get_fake_migration_context_with_pci_devs()
        pci_mapping = mig_ctx.get_pci_mapping_for_migration(True)
        self.assertDictEqual(
            {mig_ctx.new_pci_devices[0].address: mig_ctx.old_pci_devices[0]},
            pci_mapping)


class TestMigrationContextRemote(test_objects._RemoteTest,
                                 _TestMigrationContext):
    pass
