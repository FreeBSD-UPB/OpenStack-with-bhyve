# Copyright (c) 2014 OpenStack Foundation.
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

import os
import re

from hacking import core
from neutron_lib.hacking import checks


def flake8ext(f):
    """Decorator to indicate flake8 extension.

    This is borrowed from hacking.core.flake8ext(), but at now it is used
    only for unit tests to know which are neutron flake8 extensions.
    """
    f.name = __name__
    return f


# Guidelines for writing new hacking checks
#
#  - Use only for Neutron specific tests. OpenStack general tests
#    should be submitted to the common 'hacking' module.
#  - Pick numbers in the range N3xx. Find the current test with
#    the highest allocated number and then pick the next value.
#  - Keep the test method code in the source file ordered based
#    on the N3xx value.
#  - List the new rule in the top level HACKING.rst file
#  - Add test cases for each new rule to
#    neutron/tests/unit/hacking/test_checks.py


unittest_imports_dot = re.compile(r"\bimport[\s]+unittest\b")
unittest_imports_from = re.compile(r"\bfrom[\s]+unittest\b")
filter_match = re.compile(r".*filter\(lambda ")

tests_imports_dot = re.compile(r"\bimport[\s]+neutron.tests\b")
tests_imports_from1 = re.compile(r"\bfrom[\s]+neutron.tests\b")
tests_imports_from2 = re.compile(r"\bfrom[\s]+neutron[\s]+import[\s]+tests\b")


@flake8ext
def check_assert_called_once_with(logical_line, filename):
    """N322 - Try to detect unintended calls of nonexistent mock methods like:
                 assert_called_once
                 assertCalledOnceWith
                 assert_has_called
                 called_once_with
    """
    if 'neutron/tests/' in filename:
        if '.assert_called_once_with(' in logical_line:
            return
        uncased_line = logical_line.lower().replace('_', '')

        check_calls = ['.assertcalledonce', '.calledoncewith']
        if any(x for x in check_calls if x in uncased_line):
            msg = ("N322: Possible use of no-op mock method. "
                   "please use assert_called_once_with.")
            yield (0, msg)

        if '.asserthascalled' in uncased_line:
            msg = ("N322: Possible use of no-op mock method. "
                   "please use assert_has_calls.")
            yield (0, msg)


@flake8ext
def check_asserttruefalse(logical_line, filename):
    """N328 - Don't use assertEqual(True/False, observed)."""
    if 'neutron/tests/' in filename:
        if re.search(r"assertEqual\(\s*True,[^,]*(,[^,]*)?", logical_line):
            msg = ("N328: Use assertTrue(observed) instead of "
                   "assertEqual(True, observed)")
            yield (0, msg)
        if re.search(r"assertEqual\([^,]*,\s*True(,[^,]*)?", logical_line):
            msg = ("N328: Use assertTrue(observed) instead of "
                   "assertEqual(True, observed)")
            yield (0, msg)
        if re.search(r"assertEqual\(\s*False,[^,]*(,[^,]*)?", logical_line):
            msg = ("N328: Use assertFalse(observed) instead of "
                   "assertEqual(False, observed)")
            yield (0, msg)
        if re.search(r"assertEqual\([^,]*,\s*False(,[^,]*)?", logical_line):
            msg = ("N328: Use assertFalse(observed) instead of "
                   "assertEqual(False, observed)")
            yield (0, msg)


@flake8ext
def check_assertempty(logical_line, filename):
    """N330 - Enforce using assertEqual parameter ordering in case of empty
              objects.
    """
    if 'neutron/tests/' in filename:
        msg = ("N330: Use assertEqual(*empty*, observed) instead of "
               "assertEqual(observed, *empty*). *empty* contains "
               "{}, [], (), set(), '', \"\"")
        empties = r"(\[\s*\]|\{\s*\}|\(\s*\)|set\(\s*\)|'\s*'|\"\s*\")"
        reg = r"assertEqual\(([^,]*,\s*)+?%s\)\s*$" % empties
        if re.search(reg, logical_line):
            yield (0, msg)


@flake8ext
def check_assertisinstance(logical_line, filename):
    """N331 - Enforce using assertIsInstance."""
    if 'neutron/tests/' in filename:
        if re.search(r"assertTrue\(\s*isinstance\(\s*[^,]*,\s*[^,]*\)\)",
                     logical_line):
            msg = ("N331: Use assertIsInstance(observed, type) instead "
                   "of assertTrue(isinstance(observed, type))")
            yield (0, msg)


@flake8ext
def check_assertequal_for_httpcode(logical_line, filename):
    """N332 - Enforce correct oredering for httpcode in assertEqual."""
    msg = ("N332: Use assertEqual(expected_http_code, observed_http_code) "
           "instead of assertEqual(observed_http_code, expected_http_code)")
    if 'neutron/tests/' in filename:
        if re.search(r"assertEqual\(\s*[^,]*,[^,]*HTTP[^\.]*\.code\s*\)",
                     logical_line):
            yield (0, msg)


@flake8ext
def check_oslo_i18n_wrapper(logical_line, filename, noqa):
    """N340 - Check for neutron.i18n usage.

    Okay(neutron/foo/bar.py): from neutron._i18n import _
    Okay(neutron_fwaas/foo/bar.py): from neutron_fwaas._i18n import _
    N340(neutron/foo/bar.py): from neutron.i18n import _
    N340(neutron_fwaas/foo/bar.py): from neutron_fwaas.i18n import _
    N340(neutron_fwaas/foo/bar.py): from neutron.i18n import _
    N340(neutron_fwaas/foo/bar.py): from neutron._i18n import _
    Okay(neutron/foo/bar.py): from neutron.i18n import _  # noqa
    """

    if noqa:
        return

    split_line = logical_line.split()
    modulename = os.path.normpath(filename).split('/')[0]
    bad_i18n_module = '%s.i18n' % modulename

    if (len(split_line) > 1 and split_line[0] in ('import', 'from')):
        if (split_line[1] == bad_i18n_module or
            modulename != 'neutron' and split_line[1] in ('neutron.i18n',
                                                          'neutron._i18n')):
            msg = ("N340: %(found)s is found. Use %(module)s._i18n instead."
                   % {'found': split_line[1], 'module': modulename})
            yield (0, msg)


@flake8ext
def check_builtins_gettext(logical_line, tokens, filename, lines, noqa):
    """N341 - Check usage of builtins gettext _().

    Okay(neutron/foo.py): from neutron._i18n import _\n_('foo')
    N341(neutron/foo.py): _('foo')
    Okay(neutron/_i18n.py): _('foo')
    Okay(neutron/i18n.py): _('foo')
    Okay(neutron/foo.py): _('foo')  # noqa
    """

    if noqa:
        return

    modulename = os.path.normpath(filename).split('/')[0]

    if '%s/tests' % modulename in filename:
        return

    if os.path.basename(filename) in ('i18n.py', '_i18n.py'):
        return

    token_values = [t[1] for t in tokens]
    i18n_wrapper = '%s._i18n' % modulename

    if '_' in token_values:
        i18n_import_line_found = False
        for line in lines:
            split_line = [elm.rstrip(',') for elm in line.split()]
            if (len(split_line) > 1 and split_line[0] == 'from' and
                    split_line[1] == i18n_wrapper and
                    '_' in split_line):
                i18n_import_line_found = True
                break
        if not i18n_import_line_found:
            msg = ("N341: _ from python builtins module is used. "
                   "Use _ from %s instead." % i18n_wrapper)
            yield (0, msg)


@core.flake8ext
@core.off_by_default
def check_unittest_imports(logical_line):
    """N334 - Use unittest2 instead of unittest"""
    if (re.match(unittest_imports_from, logical_line) or
            re.match(unittest_imports_dot, logical_line)):
        msg = "N334: '%s' must be used instead of '%s'." % (
            logical_line.replace('unittest', 'unittest2'), logical_line)
        yield (0, msg)


@flake8ext
def check_no_imports_from_tests(logical_line, filename, noqa):
    """N343 Production code must not import from neutron.tests.*
    """
    msg = ("N343 Production code must not import from neutron.tests.*")

    if noqa:
        return

    if 'neutron/tests/' in filename:
        return

    for regex in tests_imports_dot, tests_imports_from1, tests_imports_from2:
        if re.match(regex, logical_line):
            yield(0, msg)


@flake8ext
def check_python3_no_filter(logical_line):
    """N344 - Use list comprehension instead of filter(lambda)."""

    msg = ("N344: Use list comprehension instead of "
           "filter(lambda obj: test(obj), data) on python3.")

    if filter_match.match(logical_line):
        yield(0, msg)


# TODO(boden): rehome this check to neutron-lib
@flake8ext
def check_no_sqlalchemy_event_import(logical_line, filename, noqa):
    """N346 - Use neutron_lib.db.api.sqla_listen rather than sqlalchemy."""
    if noqa:
        return
    is_import = (logical_line.startswith('import') or
                 logical_line.startswith('from'))
    if not is_import:
        return
    for kw in ('sqlalchemy', 'event'):
        if kw not in logical_line:
            return
    yield (0, "N346: Register sqlalchemy events through "
              "neutron_lib.db.api.sqla_listen so they can be cleaned up "
              "between unit tests")


def factory(register):
    checks.factory(register)
    register(check_assert_called_once_with)
    register(check_asserttruefalse)
    register(check_assertempty)
    register(check_assertisinstance)
    register(check_assertequal_for_httpcode)
    register(check_oslo_i18n_wrapper)
    register(check_builtins_gettext)
    register(check_unittest_imports)
    register(check_no_imports_from_tests)
    register(check_python3_no_filter)
    register(check_no_sqlalchemy_event_import)
