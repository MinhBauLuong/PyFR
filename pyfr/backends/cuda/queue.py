# -*- coding: utf-8 -*-

import collections

import pycuda.driver as cuda

from mpi4py import MPI

class CudaKernel(object):
    pass


class CudaComputeKernel(CudaKernel):
    pass


class CudaMPIKernel(CudaKernel):
    pass


def _is_compute_item(item):
    return isinstance(item, CudaComputeKernel)

def _is_mpi_item(item):
    return isinstance(item, CudaMPIKernel)

class CudaQueue(object):
    def __init__(self):
        # Last kernel we executed
        self._last = None

        # CUDA stream and MPI request list
        self._stream  = cuda.Stream()
        self._mpireqs = []

        # Items waiting to be executed
        self._items = collections.deque()

    def __lshift__(self, item):
        self._items.append(item)
        return self

    def __mod__(self, item):
        self.run()
        self._items.append(item)
        self.run()
        return self

    def _empty(self):
        return not self._items

    def _exec_item(self, item):
        if _is_compute_item(item):
            item(self._stream)
        elif _is_mpi_item(item):
            item(self._mpireqs)
        else:
            item()

        self._last = item

    def _exec_next(self):
        item  = self._items.popleft()

        # If we are at a sequence point then wait for current items
        if self._at_sequence_point(item):
            self._wait()

        # Execute the item
        self._exec_item(item)

    def _exec_nowait(self):
        while self._items and not self._at_sequence_point(self._items[0]):
            self._exec_item(self._items.popleft())

    def _wait(self):
        if _is_compute_item(self._last):
            self._stream.synchronize()
        elif _is_mpi_item(self._last):
            MPI.Prequest.Waitall(self._mpireqs)
            self._mpireqs = []
        self._last = None

    def _at_sequence_point(self, item):
        if (_is_compute_item(self._last) and not _is_compute_item(item)) or\
           (_is_mpi_item(self._last) and not _is_mpi_item(item)):
            return True
        else:
            return False

    def run(self):
        while self._items:
            self._exec_next()
        self._wait()

    @staticmethod
    def runall(queues):
        # First run any items which will not result in an implicit wait
        for q in queues:
            q._exec_nowait()

        # So long as there are items remaining in the queues
        while any(not q._empty() for q in queues):
            # Execute a (potentially) blocking item from each queue
            for q in [q for q in queues if not q._empty()]:
                q._exec_next()
                q._exec_nowait()

        # Wait for all tasks to complete
        for q in queues:
            q._wait()