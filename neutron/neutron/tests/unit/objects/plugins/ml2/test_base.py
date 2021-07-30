# Copyright (c) 2020 Red Hat, Inc.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


class SegmentAllocationDbObjTestCase(object):

    def test_get_unallocated_segments(self):
        self.assertEqual(
            [], self._test_class.get_unallocated_segments(self.context))

        obj = self.objs[0]
        obj.allocated = True
        obj.create()
        self.assertEqual(
            [], self._test_class.get_unallocated_segments(self.context))

        obj = self.objs[1]
        obj.allocated = False
        obj.create()
        allocations = self._test_class.get_unallocated_segments(self.context)
        self.assertEqual(1, len(allocations))
        self.assertEqual(obj.segmentation_id, allocations[0].segmentation_id)
