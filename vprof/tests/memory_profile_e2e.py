"""Memory profile end to end tests."""
import json
import functools
import threading
import unittest

from six.moves import builtins
from six.moves import urllib

from vprof import memory_profile
from vprof import stats_server
from vprof.tests import test_pkg

# For Python 2 and Python 3 compatibility.
try:
    import mock
except ImportError:
    from unittest import mock

_HOST, _PORT = 'localhost', 12345
_MODULE_FILENAME = 'vprof/tests/test_pkg/dummy_module.py'
_PACKAGE_PATH = 'vprof/tests/test_pkg/'
_PACKAGE_NAME = 'vprof.tests.test_pkg'


class MemoryProfileModuleEndToEndTest(unittest.TestCase):

    def setUp(self):
        program_stats = memory_profile.MemoryProfile(
            _MODULE_FILENAME).run()
        stats_handler = functools.partial(
            stats_server.StatsHandler, program_stats)
        self.server = stats_server.StatsServer(
            (_HOST, _PORT), stats_handler)
        threading.Thread(target=self.server.serve_forever).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def testRequest(self):
        response = urllib.request.urlopen(
            'http://%s:%s/profile' % (_HOST, _PORT))
        stats = json.loads(response.read().decode('utf-8'))
        self.assertEqual(stats['programName'], _MODULE_FILENAME)
        self.assertEqual(stats['totalEvents'], 1)
        first_event = stats['codeEvents'][0]
        self.assertEqual(first_event[0], 1)
        self.assertEqual(first_event[1], 1)
        self.assertEqual(first_event[3], 'line')
        self.assertEqual(first_event[4], '<module>')


class MemoryProfilePackageAsPathEndToEndTest(unittest.TestCase):

    def setUp(self):
        program_stats = memory_profile.MemoryProfile(
            _PACKAGE_PATH).run()
        stats_handler = functools.partial(
            stats_server.StatsHandler, program_stats)
        self.server = stats_server.StatsServer(
            (_HOST, _PORT), stats_handler)
        threading.Thread(target=self.server.serve_forever).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def testRequest(self):
        response = urllib.request.urlopen(
            'http://%s:%s/profile' % (_HOST, _PORT))
        stats = json.loads(response.read().decode('utf-8'))
        self.assertEqual(stats['programName'], _PACKAGE_PATH)
        first_event = stats['codeEvents'][0]
        self.assertEqual(first_event[0], 1)
        self.assertEqual(first_event[1], 1)
        self.assertEqual(first_event[3], 'line')
        self.assertEqual(first_event[4], '<module>')


class MemoryProfileImportedPackageEndToEndTest(unittest.TestCase):

    def setUp(self):
        program_stats = memory_profile.MemoryProfile(
            _PACKAGE_NAME).run()
        stats_handler = functools.partial(
            stats_server.StatsHandler, program_stats)
        self.server = stats_server.StatsServer(
            (_HOST, _PORT), stats_handler)
        threading.Thread(target=self.server.serve_forever).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def testRequest(self):
        response = urllib.request.urlopen(
            'http://%s:%s/profile' % (_HOST, _PORT))
        stats = json.loads(response.read().decode('utf-8'))
        self.assertEqual(stats['programName'], _PACKAGE_NAME)
        first_event = stats['codeEvents'][0]
        self.assertEqual(first_event[0], 1)
        self.assertEqual(first_event[1], 1)
        self.assertEqual(first_event[3], 'line')
        self.assertEqual(first_event[4], '<module>')
