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

import platform

import mock
from os_brick.initiator import connector

from nova.objects import fields as obj_fields
from nova.tests.unit.virt.libvirt.volume import test_volume
from nova.virt.libvirt.volume import fibrechannel


class LibvirtFibreChannelVolumeDriverTestCase(
        test_volume.LibvirtVolumeBaseTestCase):

    def test_libvirt_fibrechan_driver(self):
        for multipath in (True, False):
            self.flags(volume_use_multipath=multipath, group='libvirt')
            libvirt_driver = fibrechannel.LibvirtFibreChannelVolumeDriver(
                self.fake_host)
            self.assertIsInstance(libvirt_driver.connector,
                                  connector.FibreChannelConnector)
            if hasattr(libvirt_driver.connector, 'use_multipath'):
                self.assertEqual(
                    multipath, libvirt_driver.connector.use_multipath)

    def _test_libvirt_fibrechan_driver_s390(self):
        libvirt_driver = fibrechannel.LibvirtFibreChannelVolumeDriver(
                                                                self.fake_host)
        self.assertIsInstance(libvirt_driver.connector,
                              connector.FibreChannelConnectorS390X)

    @mock.patch.object(platform, 'machine',
                       return_value=obj_fields.Architecture.S390)
    def test_libvirt_fibrechan_driver_s390(self, mock_machine):
        self._test_libvirt_fibrechan_driver_s390()

    @mock.patch.object(platform, 'machine',
                       return_value=obj_fields.Architecture.S390X)
    def test_libvirt_fibrechan_driver_s390x(self, mock_machine):
        self._test_libvirt_fibrechan_driver_s390()

    def test_libvirt_fibrechan_driver_get_config(self):
        libvirt_driver = fibrechannel.LibvirtFibreChannelVolumeDriver(
                                                                self.fake_host)

        device_path = '/dev/fake-dev'
        connection_info = {'data': {'device_path': device_path}}

        conf = libvirt_driver.get_config(connection_info, self.disk_info)
        tree = conf.format_dom()

        self.assertEqual('block', tree.get('type'))
        self.assertEqual(device_path, tree.find('./source').get('dev'))
        self.assertEqual('raw', tree.find('./driver').get('type'))
        self.assertEqual('native', tree.find('./driver').get('io'))

    def test_extend_volume(self):
        device_path = '/dev/fake-dev'
        connection_info = {'data': {'device_path': device_path}}
        requested_size = 1

        libvirt_driver = fibrechannel.LibvirtFibreChannelVolumeDriver(
                                                                self.fake_host)
        libvirt_driver.connector.extend_volume = mock.MagicMock(
            return_value=requested_size)
        new_size = libvirt_driver.extend_volume(connection_info,
                                                mock.sentinel.instance,
                                                requested_size)

        self.assertEqual(requested_size, new_size)
        libvirt_driver.connector.extend_volume.assert_called_once_with(
           connection_info['data'])
