"""Module for memory profiling."""
import gc
import inspect
import os
import operator
import psutil
import re
import runpy
import sys

from collections import deque
from collections import Counter
from vprof import base_profile

try:
    import __builtin__ as builtins
except ImportError:  # __builtin__ was renamed to builtins in Python 3.
    import builtins

_BYTES_IN_MB = 1024 * 1024


def _remove_duplicates(objects):
    """Removes duplicate objects.

    Taken from http://www.peterbe.com/plog/uniqifiers-benchmark.
    """
    seen, uniq = set(), []
    for obj in objects:
        obj_id = id(obj)
        if obj_id in seen:
            continue
        seen.add(obj_id)
        uniq.append(obj)
    return uniq


def _get_in_memory_objects():
    """Returns all objects in memory."""
    gc.collect()
    return gc.get_objects()


def _process_in_memory_objects(objects):
    """Processes objects tracked by GC.

    Processing is done in separate function to avoid generating overhead.
    """
    return _remove_duplicates(obj for obj in objects if not inspect.isframe(obj))


def _get_memory_usage_for_process(pid):
    """Returns memory usage for process specified by pid."""
    memory_info = psutil.Process(pid).memory_info()
    return memory_info.rss


def _get_object_count_by_type(objects):
    """Counts Python objects by type."""
    return Counter(map(type, objects))


def _get_obj_count_difference(objs1, objs2):
    """Returns count difference in two collections of Python objects."""
    clean_obj_list1 = _process_in_memory_objects(objs1)
    clean_obj_list2 = _process_in_memory_objects(objs2)
    obj_count_1 = _get_object_count_by_type(clean_obj_list1)
    obj_count_2 = _get_object_count_by_type(clean_obj_list2)
    return obj_count_1 - obj_count_2


def _format_obj_count(obj_count):
    """Formats object count."""
    result = []
    regex = re.compile(r'<(?P<type>\w+) \'(?P<name>\S+)\'>')
    for obj_type, obj_count in obj_count.items():
        if obj_count != 0:
            match = re.findall(regex, repr(obj_type))
            _, name = match[0]
            result.append((name, obj_count))
    return sorted(result, key=operator.itemgetter(1), reverse=True)


class _CodeEventsTracker(object):
    """Tracks specified events during code execution.

    Class that contains all logic related to measuring memory usage after
    specified events occur during Python program execution.
    """

    def __init__(self):
        self._all_code = set()
        self._events_list = deque()
        self._original_trace_function = sys.gettrace()
        self._pid = os.getpid()
        self._resulting_events = []
        self.mem_overhead = None

    def add_code(self, code):
        """Recursively adds code to be examined."""
        if code not in self._all_code:
            self._all_code.add(code)
            for subcode in filter(inspect.iscode, code.co_consts):
                self.add_code(subcode)

    def __enter__(self):
        """Enables events tracker."""
        sys.settrace(self._trace_memory_usage)
        return self

    def __exit__(self, exc_type, exc_val, exc_tbf):
        """Disables events tracker."""
        sys.settrace(self._original_trace_function)

    def _trace_memory_usage(self, frame, event, arg):  #pylint: disable=unused-argument
        """Tracks memory usage when specified events occur."""
        if event == 'line' and frame.f_code in self._all_code:
            curr_memory = _get_memory_usage_for_process(self._pid)
            self._events_list.append(
                (frame.f_lineno, curr_memory,
                 frame.f_code.co_name, frame.f_code.co_filename))
        return self._trace_memory_usage

    @property
    def code_events(self):
        """Returns processed code events."""
        if self._resulting_events:
            return self._resulting_events
        for i, (lineno, mem, func, fname) in enumerate(self._events_list):
            mem_in_mb = float(mem - self.mem_overhead) / _BYTES_IN_MB
            if (self._resulting_events and
                    self._resulting_events[-1][0] == lineno and
                    self._resulting_events[-1][2] == func and
                    self._resulting_events[-1][3] == fname and
                    self._resulting_events[-1][1] < mem_in_mb):
                self._resulting_events[-1][1] = mem_in_mb
            else:
                self._resulting_events.append(
                    [i + 1, lineno, mem_in_mb, func, fname])
        return self._resulting_events

    @property
    def obj_overhead(self):
        """Returns all objects that are counted as profiler overhead.

        Objects are hardcoded for convenience.
        """
        overhead = [
            self,
            self._resulting_events,
            self._events_list,
            self._all_code
        ]
        overhead_count = _get_object_count_by_type(overhead)
        # One for reference to __dict__ and one for reference to
        # the current module.
        overhead_count[dict] += 2
        return overhead_count

    def compute_mem_overhead(self):
        """Computes memory overhead at current time."""
        self.mem_overhead = (_get_memory_usage_for_process(self._pid) -
                             builtins.initial_rss_size)


class MemoryProfile(base_profile.BaseProfile):
    """Memory profiler wrapper.

    Runs memory profiler and processes all obtained stats.
    """

    def run_as_package_path(self):
        """Runs program as package specified with file path."""
        pkg_code = base_profile.get_package_code(
            self._run_object, name_is_path=True)
        with _CodeEventsTracker() as prof:
            for _, compiled_code in pkg_code.values():
                prof.add_code(compiled_code)
            try:
                prof.compute_mem_overhead()
                runpy.run_path(self._run_object, run_name='__main__')
            except SystemExit:
                pass
        return prof

    def run_as_module(self):
        """Runs program as module."""
        try:
            with open(self._run_object, 'rb') as srcfile,\
                _CodeEventsTracker() as prof:
                code = compile(srcfile.read(), self._run_object, 'exec')
                prof.add_code(code)
                prof.compute_mem_overhead()
                exec(code, self._globs, None)
        except SystemExit:
            pass
        return prof

    def run_as_package_in_namespace(self):
        """Runs object as package in Python namespace."""
        pkg_code = base_profile.get_package_code(self._run_object)
        with _CodeEventsTracker() as prof:
            for _, compiled_code in pkg_code.values():
                prof.add_code(compiled_code)
            try:
                prof.compute_mem_overhead()
                runpy.run_module(self._run_object, run_name='__main__')
            except SystemExit:
                pass
        return prof

    def run_as_function(self):
        """Runs object as function."""
        with _CodeEventsTracker() as prof:
            prof.add_code(self._run_object.__code__)
            prof.compute_mem_overhead()
            self._run_object(*self._run_args, **self._run_kwargs)
        return prof

    def run(self):
        """Collects memory stats for specified Python program."""
        run_dispatcher = self.get_run_dispatcher()
        existing_objects = _get_in_memory_objects()
        prof = run_dispatcher()
        new_objects = _get_in_memory_objects()

        new_obj_count = _get_obj_count_difference(new_objects, existing_objects)
        result_obj_count = new_obj_count - prof.obj_overhead

        # existing_objects list is also profiler overhead
        result_obj_count[list] -= 1
        pretty_obj_count = _format_obj_count(result_obj_count)
        return {
            'objectName': self._object_name,  # Set on run dispatching.
            'codeEvents': prof.code_events,
            'totalEvents': len(prof.code_events),
            'objectsCount': pretty_obj_count
        }
