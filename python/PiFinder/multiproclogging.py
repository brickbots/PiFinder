#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This module provides a sink process for all logging in PiFinder

Due to `logging` not being compatible out of the box with concurrency using processes, the logging cookbook recommends to use
the approach implemented here: A single process that is fed log records using `Queue`s.
"""

import multiprocessing.queues
from pathlib import Path
from multiprocessing import Queue, Process
import multiprocessing
from queue import Empty
from time import sleep
from typing import TextIO, List, Optional
import json5
import logging
import logging.config
import logging.handlers


class MultiprocLogging:
    """
    Class implementing the approach for multi process logging, explained here:
    https://docs.python.org/dev/howto/logging-cookbook.html#logging-to-a-single-file-from-multiple-processes

    log_conf: the logging configuration file to read in and apply (when instantiating)
    out_file: the log file to write to.
    formatter: the format specification used to log records to the file.

    Shortcomings
    ------------
     * The implememtation assumes that the log configuration read in is propagated to new processes. **This is not true on Windows!**

    Prerequisite
    ------------
      * You should have all your logging configuration in a single configuration file, that applies to all processes!

    How to use this
    ===============

     0) In the main process of your software, create an instance of this class,
        passing in the location of your logging configuration file and which logfile to use.
     1) Retrieve the needed queues from this instance, using `get_queue()`.
        The respective queues need to be passed on to the processes, see 3)
     2) Before spawning any other processes, `start()` the log storage in a separate process.
     2) when starting up each process, pass in the queues retrieved in step 1) for each process a different queue.
     3) In the newly running process, call `MultiprocLogging.configurer(queue)`, which then applies the logging configuration to forward
        to the log process writing to the file.

    Note that timestamps are generated on creation of the log record (when you call `debug()` and friends), they may not be in order in the log file though.
    """

    def __init__(
        self,
        log_conf: Optional[Path] = None,
        out_file: Optional[Path] = None,
        formatter: str = "%(asctime)s %(processName)s-%(name)s:%(levelname)s:%(message)s",
    ):
        self._queues: List[Queue] = []
        self._initial_queue: Optional[Queue] = None
        self._log_conf_file = log_conf
        self._log_output_file = out_file
        self._formatter = formatter
        self._proc: Optional[Process] = None

        self.apply_config()

    def apply_config(self):
        if self._log_conf_file is not None:
            with open(self._log_conf_file, "r") as f:
                self.read_config(f)

    def start(self, initial_queue: Optional[Queue] = None):
        assert self._proc is None, "You should only start once!"
        assert (
            len(self._queues) >= 1 or self._initial_queue is not None
        ), "No queues in use. You should have requested at least one queue."
        if self._initial_queue is not None:
             self._queues.append(self._initial_queue)
        self._proc = Process(
            target=self._run_sink,
            args=(
                self._log_output_file,
                self._queues,
            ),
        )
        # Start separate process that consumes from the queues.
        self._proc.start()
        # Now in this process we can divert logging to the newly created class
        queue = self.get_queue()
        MultiprocLogging.configurer(queue)

    def join(self):
        assert self._proc is not None, "You didn't start first!"
        # Signal to _run_sink, that it should stop.
        self._queues[0].put(None)
        self._proc.join()

    def _run_sink(self, output: Path, queues: List[Queue]):
        """
        This is the process that consumes every log message (sink)

        All log messages send here over queues will be passed by this method to the log handlers that write it out to the single log file.
        This is started in __init__.
        """

        # configure logging to store everything in output
        h = logging.handlers.WatchedFileHandler(output)
        f = logging.Formatter(self._formatter)
        h.setFormatter(f)
        logging.getLogger().addHandler(h)

        # Consume log messages and store them in output log file
        nqueues = len(queues)
        while True:
            empties = 0
            for q in queues:
                try:
                    rec = q.get(block=False)
                    if rec is None:  # Received End Marker
                        return
                    logger = logging.getLogger(rec.name)
                    logger.handle(rec)
                except Empty:
                    empties += 1
            if empties == nqueues:
                sleep(0.1)  # No log messages in any queue, so sleep 100 ms.

    def get_queue(self):
        """
        Retreive a new queue, for creating another process

        This method will register the queue so that the process that writes out log messages to a single log file, will consume log records from it.
        """

        new_queue = Queue()
        self._queues.append(new_queue)
        return new_queue

    def get_initial_queue(self):
        """
        Retrieve a new queue, that can be used to log to (using `configurer()`) BEFORE starting MultiprocLogging

        This is to catch

        """
        if self._initial_queue is None:
            new_queue = Queue()
            self._initial_queue = new_queue
        return self._initial_queue

    @staticmethod
    def configurer(queue: Queue):
        """
        Setup the passed queue as target for log messages

        This method needs to be called once in each process, so that log records get forwarded to the single process writing
        log messages.
        """
        assert queue is not None, "You passed a None to configurer! You cannot do that"
        assert isinstance(queue, multiprocessing.queues.Queue), "That's not a Queue! You have to pass a queue" 

        h = logging.handlers.QueueHandler(queue)
        root = logging.getLogger()
        root.addHandler(h)

    def set_log_conf_file(self, config: Path) -> None:
        self._log_conf_file = config
        if not self._log_conf_file.exists():
            raise FileNotFoundError(
                "Configuration file passed to set_log_conf_file() does not exist."
            )

        # Read in configuration
        with open(self._log_conf_file, "r") as f:
            self.read_config(f)

    def get_log_conf_file(self) -> Optional[Path]:
        """
        Retrieve the path of the log file, that is used.
        """
        return self._log_conf_file

    def read_config(self, file: TextIO):
        """
        Read logging configuration from the specified file handle and apply it.
        """
        config = json5.load(file)
        logging.config.dictConfig(config)
