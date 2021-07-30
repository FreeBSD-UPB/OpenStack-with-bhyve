# Copyright 2015 Red Hat, Inc.
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

"""
In order to save gate resources, test paths that have similar
environmental requirements to the functional path are marked for
discovery.
"""

import os.path

from neutron.common import eventlet_utils


eventlet_utils.monkey_patch()


def load_tests(loader, tests, pattern):
    this_dir = os.path.dirname(__file__)
    new_tests = loader.discover(start_dir=this_dir, pattern=pattern)
    tests.addTests(new_tests)
    return tests
