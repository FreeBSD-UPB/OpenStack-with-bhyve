# Copyright (c) 2015 EMC Corporation
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

import mock

from nova.tests.unit.virt.libvirt.volume import test_volume
from nova.virt.libvirt.volume import scaleio


class LibvirtScaleIOVolumeDriverTestCase(
        test_volume.LibvirtVolumeBaseTestCase):

    def test_libvirt_scaleio_driver_connect(self):
        def brick_conn_vol(data):
            return {'path': '/dev/vol01'}

        sio = scaleio.LibvirtScaleIOVolumeDriver(self.fake_host)
        sio.connector.connect_volume = brick_conn_vol
        disk_info = {'path': '/dev/vol01', 'name': 'vol01'}
        conn = {'data': disk_info}
        sio.connect_volume(conn, mock.sentinel.instance)
        self.assertEqual('/dev/vol01',
                         conn['data']['device_path'])

    def test_libvirt_scaleio_driver_get_config(self):
        sio = scaleio.LibvirtScaleIOVolumeDriver(self.fake_host)
        conn = {'data': {'device_path': '/dev/vol01'}}
        conf = sio.get_config(conn, self.disk_info)
        self.assertEqual('block', conf.source_type)
        self.assertEqual('/dev/vol01', conf.source_path)

    def test_libvirt_scaleio_driver_disconnect(self):
        sio = scaleio.LibvirtScaleIOVolumeDriver(self.fake_host)
        sio.connector.disconnect_volume = mock.MagicMock()
        conn = {'data': mock.sentinel.conn_data}
        sio.disconnect_volume(conn, mock.sentinel.instance)
        sio.connector.disconnect_volume.assert_called_once_with(
            mock.sentinel.conn_data, None)

    def test_libvirt_scaleio_driver_extend_volume(self):
        def brick_extend_vol(data):
            return data['size']

        extended_vol_size = 8
        sio = scaleio.LibvirtScaleIOVolumeDriver(self.fake_host)
        disk_info = {'size': extended_vol_size,
                     'name': 'vol01',
                     'device_path': '/dev/vol01'}
        conn = {'data': disk_info}
        with mock.patch.object(sio.connector,
                               'extend_volume',
                               side_effect=brick_extend_vol):
            self.assertEqual(extended_vol_size,
                             sio.extend_volume(conn, mock.sentinel.instance,
                                               extended_vol_size))
