# Copyright (c) 2013 Intel, Inc.
# Copyright (c) 2013 OpenStack Foundation
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

from oslo_config import cfg

pci_group = cfg.OptGroup(
    name='pci',
    title='PCI passthrough options')

pci_opts = [
    cfg.MultiStrOpt('alias',
        default=[],
        deprecated_name='pci_alias',
        deprecated_group='DEFAULT',
        help="""
An alias for a PCI passthrough device requirement.

This allows users to specify the alias in the extra specs for a flavor, without
needing to repeat all the PCI property requirements.

This should be configured for the ``nova-api`` service and, assuming you wish
to use move operations, for each ``nova-compute`` service.

Possible Values:

* A dictionary of JSON values which describe the aliases. For example::

    alias = {
      "name": "QuickAssist",
      "product_id": "0443",
      "vendor_id": "8086",
      "device_type": "type-PCI",
      "numa_policy": "required"
    }

  This defines an alias for the Intel QuickAssist card. (multi valued). Valid
  key values are :

  ``name``
    Name of the PCI alias.

  ``product_id``
    Product ID of the device in hexadecimal.

  ``vendor_id``
    Vendor ID of the device in hexadecimal.

  ``device_type``
    Type of PCI device. Valid values are: ``type-PCI``, ``type-PF`` and
    ``type-VF``.

  ``numa_policy``
    Required NUMA affinity of device. Valid values are: ``legacy``,
    ``preferred`` and ``required``.

* Supports multiple aliases by repeating the option (not by specifying
  a list value)::

    alias = {
      "name": "QuickAssist-1",
      "product_id": "0443",
      "vendor_id": "8086",
      "device_type": "type-PCI",
      "numa_policy": "required"
    }
    alias = {
      "name": "QuickAssist-2",
      "product_id": "0444",
      "vendor_id": "8086",
      "device_type": "type-PCI",
      "numa_policy": "required"
    }
"""),
    cfg.MultiStrOpt('passthrough_whitelist',
        default=[],
        deprecated_name='pci_passthrough_whitelist',
        deprecated_group='DEFAULT',
        help="""
White list of PCI devices available to VMs.

Possible values:

* A JSON dictionary which describe a whitelisted PCI device. It should take
  the following format::

    ["vendor_id": "<id>",] ["product_id": "<id>",]
    ["address": "[[[[<domain>]:]<bus>]:][<slot>][.[<function>]]" |
     "devname": "<name>",]
    {"<tag>": "<tag_value>",}

  Where ``[`` indicates zero or one occurrences, ``{`` indicates zero or
  multiple occurrences, and ``|`` mutually exclusive options. Note that any
  missing fields are automatically wildcarded.

  Valid key values are :

  ``vendor_id``
    Vendor ID of the device in hexadecimal.

  ``product_id``
    Product ID of the device in hexadecimal.

  ``address``
    PCI address of the device. Both traditional glob style and regular
    expression syntax is supported.

  ``devname``
    Device name of the device (for e.g. interface name). Not all PCI devices
    have a name.

  ``<tag>``
    Additional ``<tag>`` and ``<tag_value>`` used for matching PCI devices.
    Supported ``<tag>`` values are :

    - ``physical_network``
    - ``trusted``

  Valid examples are::

    passthrough_whitelist = {"devname":"eth0",
                             "physical_network":"physnet"}
    passthrough_whitelist = {"address":"*:0a:00.*"}
    passthrough_whitelist = {"address":":0a:00.",
                             "physical_network":"physnet1"}
    passthrough_whitelist = {"vendor_id":"1137",
                             "product_id":"0071"}
    passthrough_whitelist = {"vendor_id":"1137",
                             "product_id":"0071",
                             "address": "0000:0a:00.1",
                             "physical_network":"physnet1"}
    passthrough_whitelist = {"address":{"domain": ".*",
                                        "bus": "02", "slot": "01",
                                        "function": "[2-7]"},
                             "physical_network":"physnet1"}
    passthrough_whitelist = {"address":{"domain": ".*",
                                        "bus": "02", "slot": "0[1-2]",
                                        "function": ".*"},
                             "physical_network":"physnet1"}
    passthrough_whitelist = {"devname": "eth0", "physical_network":"physnet1",
                             "trusted": "true"}

  The following are invalid, as they specify mutually exclusive options::

    passthrough_whitelist = {"devname":"eth0",
                             "physical_network":"physnet",
                             "address":"*:0a:00.*"}

* A JSON list of JSON dictionaries corresponding to the above format. For
  example::

    passthrough_whitelist = [{"product_id":"0001", "vendor_id":"8086"},
                             {"product_id":"0002", "vendor_id":"8086"}]
""")
]


def register_opts(conf):
    conf.register_group(pci_group)
    conf.register_opts(pci_opts, group=pci_group)


def list_opts():
    return {pci_group: pci_opts}
