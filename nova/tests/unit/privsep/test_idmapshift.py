# Copyright 2014 Rackspace, Andrew Melton
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import fixtures
import mock
from six.moves import StringIO

import nova.privsep.idmapshift
from nova import test


def join_side_effect(root, *args):
    path = root
    if root != '/':
        path += '/'
    path += '/'.join(args)
    return path


class FakeStat(object):
    def __init__(self, uid, gid):
        self.st_uid = uid
        self.st_gid = gid


class BaseTestCase(test.NoDBTestCase):
    def setUp(self):
        super(BaseTestCase, self).setUp()
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', StringIO()))

        self.uid_maps = [(0, 10000, 10), (10, 20000, 1000)]
        self.gid_maps = [(0, 10000, 10), (10, 20000, 1000)]


class FindTargetIDTestCase(BaseTestCase):
    def test_find_target_id_range_1_first(self):
        actual_target = nova.privsep.idmapshift.find_target_id(
            0, self.uid_maps, nova.privsep.idmapshift.NOBODY_ID, dict())
        self.assertEqual(10000, actual_target)

    def test_find_target_id_inside_range_1(self):
        actual_target = nova.privsep.idmapshift.find_target_id(
            2, self.uid_maps, nova.privsep.idmapshift.NOBODY_ID, dict())
        self.assertEqual(10002, actual_target)

    def test_find_target_id_range_2_first(self):
        actual_target = nova.privsep.idmapshift.find_target_id(
            10, self.uid_maps, nova.privsep.idmapshift.NOBODY_ID, dict())
        self.assertEqual(20000, actual_target)

    def test_find_target_id_inside_range_2(self):
        actual_target = nova.privsep.idmapshift.find_target_id(
            100, self.uid_maps, nova.privsep.idmapshift.NOBODY_ID, dict())
        self.assertEqual(20090, actual_target)

    def test_find_target_id_outside_range(self):
        actual_target = nova.privsep.idmapshift.find_target_id(
            10000, self.uid_maps, nova.privsep.idmapshift.NOBODY_ID, dict())
        self.assertEqual(nova.privsep.idmapshift.NOBODY_ID, actual_target)

    def test_find_target_id_no_mappings(self):
        actual_target = nova.privsep.idmapshift.find_target_id(
            0, [], nova.privsep.idmapshift.NOBODY_ID, dict())
        self.assertEqual(nova.privsep.idmapshift.NOBODY_ID, actual_target)

    def test_find_target_id_updates_memo(self):
        memo = dict()
        nova.privsep.idmapshift.find_target_id(
            0, self.uid_maps, nova.privsep.idmapshift.NOBODY_ID, memo)
        self.assertIn(0, memo)
        self.assertEqual(10000, memo[0])

    def test_find_target_guest_id_greater_than_count(self):
        uid_maps = [(500, 10000, 10)]

        # Below range
        actual_target = nova.privsep.idmapshift.find_target_id(
            499, uid_maps, nova.privsep.idmapshift.NOBODY_ID, dict())
        self.assertEqual(nova.privsep.idmapshift.NOBODY_ID, actual_target)

        # Match
        actual_target = nova.privsep.idmapshift.find_target_id(
            501, uid_maps, nova.privsep.idmapshift.NOBODY_ID, dict())
        self.assertEqual(10001, actual_target)

        # Beyond range
        actual_target = nova.privsep.idmapshift.find_target_id(
            510, uid_maps, nova.privsep.idmapshift.NOBODY_ID, dict())
        self.assertEqual(nova.privsep.idmapshift.NOBODY_ID, actual_target)


class ShiftPathTestCase(BaseTestCase):
    @mock.patch('os.lchown')
    @mock.patch('os.lstat')
    def test_shift_path(self, mock_lstat, mock_lchown):
        mock_lstat.return_value = FakeStat(0, 0)
        nova.privsep.idmapshift.shift_path(
            '/test/path', self.uid_maps, self.gid_maps,
            nova.privsep.idmapshift.NOBODY_ID, dict(), dict())
        mock_lstat.assert_has_calls([mock.call('/test/path')])
        mock_lchown.assert_has_calls([mock.call('/test/path', 10000, 10000)])


class ShiftDirTestCase(BaseTestCase):
    @mock.patch('nova.privsep.idmapshift.shift_path')
    @mock.patch('os.path.join')
    @mock.patch('os.walk')
    def test_shift_dir(self, mock_walk, mock_join, mock_shift_path):
        mock_walk.return_value = [('/', ['a', 'b'], ['c', 'd'])]
        mock_join.side_effect = join_side_effect

        nova.privsep.idmapshift.shift_dir('/', self.uid_maps, self.gid_maps,
                             nova.privsep.idmapshift.NOBODY_ID)

        files = ['a', 'b', 'c', 'd']
        mock_walk.assert_has_calls([mock.call('/')])
        mock_join_calls = [mock.call('/', x) for x in files]
        mock_join.assert_has_calls(mock_join_calls)

        args = (self.uid_maps, self.gid_maps,
                nova.privsep.idmapshift.NOBODY_ID)
        kwargs = dict(uid_memo=dict(), gid_memo=dict())
        shift_path_calls = [mock.call('/', *args, **kwargs)]
        shift_path_calls += [mock.call('/' + x, *args, **kwargs)
                             for x in files]
        mock_shift_path.assert_has_calls(shift_path_calls)


class ConfirmPathTestCase(test.NoDBTestCase):
    @mock.patch('os.lstat')
    def test_confirm_path(self, mock_lstat):
        uid_ranges = [(1000, 1999)]
        gid_ranges = [(300, 399)]
        mock_lstat.return_value = FakeStat(1000, 301)

        result = nova.privsep.idmapshift.confirm_path(
            '/test/path', uid_ranges, gid_ranges, 50000)

        mock_lstat.assert_has_calls([mock.call('/test/path')])
        self.assertTrue(result)

    @mock.patch('os.lstat')
    def test_confirm_path_nobody(self, mock_lstat):
        uid_ranges = [(1000, 1999)]
        gid_ranges = [(300, 399)]
        mock_lstat.return_value = FakeStat(50000, 50000)

        result = nova.privsep.idmapshift.confirm_path(
            '/test/path', uid_ranges, gid_ranges, 50000)

        mock_lstat.assert_has_calls([mock.call('/test/path')])
        self.assertTrue(result)

    @mock.patch('os.lstat')
    def test_confirm_path_uid_mismatch(self, mock_lstat):
        uid_ranges = [(1000, 1999)]
        gid_ranges = [(300, 399)]
        mock_lstat.return_value = FakeStat(0, 301)

        result = nova.privsep.idmapshift.confirm_path(
            '/test/path', uid_ranges, gid_ranges, 50000)

        mock_lstat.assert_has_calls([mock.call('/test/path')])
        self.assertFalse(result)

    @mock.patch('os.lstat')
    def test_confirm_path_gid_mismatch(self, mock_lstat):
        uid_ranges = [(1000, 1999)]
        gid_ranges = [(300, 399)]
        mock_lstat.return_value = FakeStat(1000, 0)

        result = nova.privsep.idmapshift.confirm_path(
            '/test/path', uid_ranges, gid_ranges, 50000)

        mock_lstat.assert_has_calls([mock.call('/test/path')])
        self.assertFalse(result)

    @mock.patch('os.lstat')
    def test_confirm_path_uid_nobody(self, mock_lstat):
        uid_ranges = [(1000, 1999)]
        gid_ranges = [(300, 399)]
        mock_lstat.return_value = FakeStat(50000, 301)

        result = nova.privsep.idmapshift.confirm_path(
            '/test/path', uid_ranges, gid_ranges, 50000)

        mock_lstat.assert_has_calls([mock.call('/test/path')])
        self.assertTrue(result)

    @mock.patch('os.lstat')
    def test_confirm_path_gid_nobody(self, mock_lstat):
        uid_ranges = [(1000, 1999)]
        gid_ranges = [(300, 399)]
        mock_lstat.return_value = FakeStat(1000, 50000)

        result = nova.privsep.idmapshift.confirm_path(
            '/test/path', uid_ranges, gid_ranges, 50000)

        mock_lstat.assert_has_calls([mock.call('/test/path')])
        self.assertTrue(result)


class ConfirmDirTestCase(BaseTestCase):
    def setUp(self):
        super(ConfirmDirTestCase, self).setUp()
        self.uid_map_ranges = nova.privsep.idmapshift.get_ranges(self.uid_maps)
        self.gid_map_ranges = nova.privsep.idmapshift.get_ranges(self.gid_maps)

    @mock.patch('nova.privsep.idmapshift.confirm_path')
    @mock.patch('os.path.join')
    @mock.patch('os.walk')
    def test_confirm_dir(self, mock_walk, mock_join, mock_confirm_path):
        mock_walk.return_value = [('/', ['a', 'b'], ['c', 'd'])]
        mock_join.side_effect = join_side_effect
        mock_confirm_path.return_value = True

        nova.privsep.idmapshift.confirm_dir('/', self.uid_maps, self.gid_maps,
                               nova.privsep.idmapshift.NOBODY_ID)

        files = ['a', 'b', 'c', 'd']
        mock_walk.assert_has_calls([mock.call('/')])
        mock_join_calls = [mock.call('/', x) for x in files]
        mock_join.assert_has_calls(mock_join_calls)

        args = (self.uid_map_ranges, self.gid_map_ranges,
                nova.privsep.idmapshift.NOBODY_ID)
        confirm_path_calls = [mock.call('/', *args)]
        confirm_path_calls += [mock.call('/' + x, *args)
                               for x in files]
        mock_confirm_path.assert_has_calls(confirm_path_calls)

    @mock.patch('nova.privsep.idmapshift.confirm_path')
    @mock.patch('os.path.join')
    @mock.patch('os.walk')
    def test_confirm_dir_short_circuit_root(self, mock_walk, mock_join,
                                            mock_confirm_path):
        mock_walk.return_value = [('/', ['a', 'b'], ['c', 'd'])]
        mock_join.side_effect = join_side_effect
        mock_confirm_path.return_value = False

        nova.privsep.idmapshift.confirm_dir('/', self.uid_maps, self.gid_maps,
                               nova.privsep.idmapshift.NOBODY_ID)

        args = (self.uid_map_ranges, self.gid_map_ranges,
                nova.privsep.idmapshift.NOBODY_ID)
        confirm_path_calls = [mock.call('/', *args)]
        mock_confirm_path.assert_has_calls(confirm_path_calls)

    @mock.patch('nova.privsep.idmapshift.confirm_path')
    @mock.patch('os.path.join')
    @mock.patch('os.walk')
    def test_confirm_dir_short_circuit_file(self, mock_walk, mock_join,
                                            mock_confirm_path):
        mock_walk.return_value = [('/', ['a', 'b'], ['c', 'd'])]
        mock_join.side_effect = join_side_effect

        def confirm_path_side_effect(path, *args):
            if 'a' in path:
                return False
            return True

        mock_confirm_path.side_effect = confirm_path_side_effect

        nova.privsep.idmapshift.confirm_dir('/', self.uid_maps, self.gid_maps,
                               nova.privsep.idmapshift.NOBODY_ID)

        mock_walk.assert_has_calls([mock.call('/')])
        mock_join.assert_has_calls([mock.call('/', 'a')])

        args = (self.uid_map_ranges, self.gid_map_ranges,
                nova.privsep.idmapshift.NOBODY_ID)
        confirm_path_calls = [mock.call('/', *args),
                              mock.call('/' + 'a', *args)]
        mock_confirm_path.assert_has_calls(confirm_path_calls)

    @mock.patch('nova.privsep.idmapshift.confirm_path')
    @mock.patch('os.path.join')
    @mock.patch('os.walk')
    def test_confirm_dir_short_circuit_dir(self, mock_walk, mock_join,
                                            mock_confirm_path):
        mock_walk.return_value = [('/', ['a', 'b'], ['c', 'd'])]
        mock_join.side_effect = join_side_effect

        def confirm_path_side_effect(path, *args):
            if 'c' in path:
                return False
            return True

        mock_confirm_path.side_effect = confirm_path_side_effect

        nova.privsep.idmapshift.confirm_dir('/', self.uid_maps, self.gid_maps,
                               nova.privsep.idmapshift.NOBODY_ID)

        files = ['a', 'b', 'c']
        mock_walk.assert_has_calls([mock.call('/')])
        mock_join_calls = [mock.call('/', x) for x in files]
        mock_join.assert_has_calls(mock_join_calls)

        args = (self.uid_map_ranges, self.gid_map_ranges,
                nova.privsep.idmapshift.NOBODY_ID)
        confirm_path_calls = [mock.call('/', *args)]
        confirm_path_calls += [mock.call('/' + x, *args)
                               for x in files]
        mock_confirm_path.assert_has_calls(confirm_path_calls)


class IntegrationTestCase(BaseTestCase):
    @mock.patch('os.lchown')
    @mock.patch('os.lstat')
    @mock.patch('os.path.join')
    @mock.patch('os.walk')
    def test_integrated_shift_dir(self, mock_walk, mock_join, mock_lstat,
                                  mock_lchown):
        mock_walk.return_value = [('/tmp/test', ['a', 'b', 'c'], ['d']),
                                  ('/tmp/test/d', ['1', '2'], [])]
        mock_join.side_effect = join_side_effect

        def lstat(path):
            stats = {
                't': FakeStat(0, 0),
                'a': FakeStat(0, 0),
                'b': FakeStat(0, 2),
                'c': FakeStat(30000, 30000),
                'd': FakeStat(100, 100),
                '1': FakeStat(0, 100),
                '2': FakeStat(100, 100),
            }
            return stats[path[-1]]

        mock_lstat.side_effect = lstat

        nova.privsep.idmapshift.shift_dir('/tmp/test', self.uid_maps,
                                          self.gid_maps,
                                          nova.privsep.idmapshift.NOBODY_ID)

        lchown_calls = [
            mock.call('/tmp/test', 10000, 10000),
            mock.call('/tmp/test/a', 10000, 10000),
            mock.call('/tmp/test/b', 10000, 10002),
            mock.call('/tmp/test/c', nova.privsep.idmapshift.NOBODY_ID,
                      nova.privsep.idmapshift.NOBODY_ID),
            mock.call('/tmp/test/d', 20090, 20090),
            mock.call('/tmp/test/d/1', 10000, 20090),
            mock.call('/tmp/test/d/2', 20090, 20090),
        ]
        mock_lchown.assert_has_calls(lchown_calls)

    @mock.patch('os.lstat')
    @mock.patch('os.path.join')
    @mock.patch('os.walk')
    def test_integrated_confirm_dir_shifted(self, mock_walk, mock_join,
                                              mock_lstat):
        mock_walk.return_value = [('/tmp/test', ['a', 'b', 'c'], ['d']),
                                  ('/tmp/test/d', ['1', '2'], [])]
        mock_join.side_effect = join_side_effect

        def lstat(path):
            stats = {
                't': FakeStat(10000, 10000),
                'a': FakeStat(10000, 10000),
                'b': FakeStat(10000, 10002),
                'c': FakeStat(nova.privsep.idmapshift.NOBODY_ID,
                              nova.privsep.idmapshift.NOBODY_ID),
                'd': FakeStat(20090, 20090),
                '1': FakeStat(10000, 20090),
                '2': FakeStat(20090, 20090),
            }
            return stats[path[-1]]

        mock_lstat.side_effect = lstat

        result = nova.privsep.idmapshift.confirm_dir(
            '/tmp/test', self.uid_maps, self.gid_maps,
            nova.privsep.idmapshift.NOBODY_ID)

        self.assertTrue(result)

    @mock.patch('os.lstat')
    @mock.patch('os.path.join')
    @mock.patch('os.walk')
    def test_integrated_confirm_dir_unshifted(self, mock_walk, mock_join,
                                            mock_lstat):
        mock_walk.return_value = [('/tmp/test', ['a', 'b', 'c'], ['d']),
                                  ('/tmp/test/d', ['1', '2'], [])]
        mock_join.side_effect = join_side_effect

        def lstat(path):
            stats = {
                't': FakeStat(0, 0),
                'a': FakeStat(0, 0),
                'b': FakeStat(0, 2),
                'c': FakeStat(30000, 30000),
                'd': FakeStat(100, 100),
                '1': FakeStat(0, 100),
                '2': FakeStat(100, 100),
            }
            return stats[path[-1]]

        mock_lstat.side_effect = lstat

        result = nova.privsep.idmapshift.confirm_dir(
            '/tmp/test', self.uid_maps, self.gid_maps,
            nova.privsep.idmapshift.NOBODY_ID)

        self.assertFalse(result)
