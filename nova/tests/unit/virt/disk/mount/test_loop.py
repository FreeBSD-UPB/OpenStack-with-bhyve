# Copyright 2012 Michael Still
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


import fixtures
import mock

from nova import test
from nova.virt.disk.mount import loop
from nova.virt.image import model as imgmodel


def _fake_noop(*args, **kwargs):
    return


class LoopTestCase(test.NoDBTestCase):
    def setUp(self):
        super(LoopTestCase, self).setUp()

        self.file = imgmodel.LocalFileImage("/some/file.qcow2",
                                            imgmodel.FORMAT_QCOW2)

    @mock.patch('nova.privsep.fs.loopsetup', return_value=('/dev/loop0', ''))
    @mock.patch('nova.privsep.fs.loopremove')
    def test_get_dev(self, mock_loopremove, mock_loopsetup):
        tempdir = self.useFixture(fixtures.TempDir()).path
        mount = loop.LoopMount(self.file, tempdir)

        # No error logged, device consumed
        self.assertTrue(mount.get_dev())
        self.assertTrue(mount.linked)
        self.assertEqual('', mount.error)
        self.assertEqual('/dev/loop0', mount.device)

        # Free
        mount.unget_dev()
        self.assertFalse(mount.linked)
        self.assertEqual('', mount.error)
        self.assertIsNone(mount.device)

    @mock.patch('nova.privsep.fs.loopsetup', return_value=('', 'doh'))
    def test_inner_get_dev_fails(self, mock_loopsetup):
        tempdir = self.useFixture(fixtures.TempDir()).path
        mount = loop.LoopMount(self.file, tempdir)

        # No error logged, device consumed
        self.assertFalse(mount._inner_get_dev())
        self.assertFalse(mount.linked)
        self.assertNotEqual('', mount.error)
        self.assertIsNone(mount.device)

        # Free
        mount.unget_dev()
        self.assertFalse(mount.linked)
        self.assertIsNone(mount.device)

    @mock.patch('nova.privsep.fs.loopsetup', return_value=('', 'doh'))
    def test_get_dev_timeout(self, mock_loopsetup):
        tempdir = self.useFixture(fixtures.TempDir()).path
        mount = loop.LoopMount(self.file, tempdir)
        self.useFixture(fixtures.MonkeyPatch('time.sleep', _fake_noop))
        self.useFixture(fixtures.MonkeyPatch(('nova.virt.disk.mount.api.'
                                              'MAX_DEVICE_WAIT'), -10))

        # Always fail to get a device
        def fake_get_dev_fails():
            return False

        mount._inner_get_dev = fake_get_dev_fails

        # Fail to get a device
        self.assertFalse(mount.get_dev())

    @mock.patch('nova.privsep.fs.loopremove')
    def test_unget_dev(self, mock_loopremove):
        tempdir = self.useFixture(fixtures.TempDir()).path
        mount = loop.LoopMount(self.file, tempdir)

        # This just checks that a free of something we don't have doesn't
        # throw an exception
        mount.unget_dev()
