#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Dataclasses to support the StarParty Server
"""

from dataclasses import dataclass, field
from time import time
from typing import Union
from collections import deque

@dataclass
class GroupEvent:
    """
    Events that go belong to a specific group for dumping to all
    connections for that group
    """
    event_time: float
    event_type: str
    event_data: str

@dataclass
class Group:
    name: str
    marks: list["Mark"] = field(default_factory=list)
    observers: list["Observer"] = field(default_factory=list)
    events: deque[GroupEvent] = deque(maxlen=20)

    def add_event(self, event_type: str, event_data:str) -> None:
        self.events.append(GroupEvent(time(), event_type, event_data))

    def get_next_event(self, event_time: float) -> Union[GroupEvent, None]:
        """
        Returns the next oldest event after event_time
        or None if no event is older than the requested
        time
        """
        if self.events[-1] <= event_time:
            # Early bail out
            return None

        for group_event in self.events:
            if group_event.event_time > event_time:
                return group_event

        # Should never get here....
        return None



@dataclass
class Position:
    ra: float = 0
    dec: float = 0


@dataclass
class Observer:
    connection_id: str
    name: str
    group: Union[Group, None] = None
    position: Position = field(default_factory=Position)


@dataclass
class ServerState:
    groups: list[Group] = field(default_factory=list)
    observers: list[Observer] = field(default_factory=list)

    def observer_count(self, group: Group) -> int:
        """
        returns the count of observers in a group
        """
        return len(group.observers)

    def add_group(self, observer: Observer, group_name: str) -> Group:
        """
        Adds a new group, then adds the observer
        to it
        """
        if observer.group:
            self.leave_group(observer)

        new_group = Group(name=group_name, observers=[observer])
        self.groups.append(new_group)
        observer.group = new_group
        return new_group

    def join_group(self, observer: Observer, group_name: str) -> bool:
        """
        Add an observer to a group
        """
        _group = self.get_group_by_name(group_name)
        if _group is None:
            return False

        if observer.group is _group:
            # already in the group!
            return True

        self.leave_group(observer)
        _group.observers.append(observer)
        observer.group = _group
        return True

    def get_group_by_name(self, group_name: str) -> Union[None, Group]:
        """
        Find a group by name
        """
        for group in self.groups:
            if group.name == group_name:
                return group

        return None

    def leave_group(self, observer: Observer) -> bool:
        """
        Called whenever someone is leaving a group.
        If the group is empty, it's deleted
        """
        if observer.group is None:
            # not in a group!
            return False

        group = observer.group

        group.observers.remove(observer)
        observer.group = None
        if self.observer_count(group) == 0:
            self.groups.remove(group)

        return True

    def list_groups(self):
        """
        Returns a list of tuples with group names and
        observer count
        """
        _ret_list = []
        for group in self.groups:
            _ret_list.append((group.name, self.observer_count(group)))

        return _ret_list


@dataclass
class Mark:
    position: Position
    obj_id: int
    name: str
    observer: Observer
