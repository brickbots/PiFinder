#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Dataclasses to support the StarParty Server
"""

from dataclasses import dataclass, field
from time import time
from typing import Union
from collections import deque
from enum import Enum
import zlib


def calc_avatar_bits(username: str) -> int:
    return zlib.crc32(username.encode("utf-8"))


class EventType(Enum):
    POSITION = "POS"
    MARK = "MRK"
    MESSAGE = "MSG"


class GroupActivity(Enum):
    HANG = "Hang"
    RACE = "Race"


@dataclass
class GroupEvent:
    """
    Events that go belong to a specific group for dumping to all
    connections for that group
    """

    event_time: float
    event_type: EventType
    event_data: tuple

    def serialize(self) -> str:
        return_string = f"{self.event_type.value}|"
        data_string = "|".join([str(x) for x in self.event_data])
        return_string += data_string
        return return_string


@dataclass
class Group:
    name: str
    activity: GroupActivity = GroupActivity.HANG
    marks: list["Mark"] = field(default_factory=list)
    observers: list["Observer"] = field(default_factory=list)
    events: deque[GroupEvent] = field(default_factory=lambda: deque(maxlen=20))

    def add_event(self, event_type: EventType, event_data: tuple) -> None:
        self.events.append(GroupEvent(time(), event_type, event_data))

    def get_next_event(self, event_time: float) -> Union[GroupEvent, None]:
        """
        Returns the next oldest event after event_time
        or None if no event is older than the requested
        time
        """
        if len(self.events) == 0:
            return None
        if self.events[-1].event_time <= event_time:
            # Early bail out
            return None

        for group_event in self.events:
            if group_event.event_time > event_time:
                return group_event

        # Should never get here....
        return None

    def serialize(self) -> str:
        return f"{self.name}|{self.activity.value}|{len(self.observers)}"


@dataclass
class Position:
    ra: float = 0
    dec: float = 0

    @classmethod
    def deserialize(cls, position_raw: str) -> "Position":
        _pos_split = position_raw.split(",")
        return cls(ra=float(_pos_split[0]), dec=float(_pos_split[1]))


@dataclass
class Observer:
    connection_id: str
    name: str
    avatar_bits: int = 0
    group: Union[Group, None] = None
    position: Position = field(default_factory=Position)

    def __post_init__(self):
        # compute the avatar_bits
        self.avatar_bits = calc_avatar_bits(self.name)

    def __str__(self) -> str:
        return self.name

    def serialize(self) -> str:
        if self.group is None:
            group_name = "Home"
        else:
            group_name = self.group.name
        return f"{self.name}|{self.avatar_bits}|{group_name}|{self.position.ra},{self.position.dec}"


@dataclass
class ServerState:
    groups: list[Group] = field(default_factory=list)
    observers: list[Observer] = field(default_factory=list)

    def observer_count(self, group: Group) -> int:
        """
        returns the count of observers in a group
        """
        return len(group.observers)

    def add_group(
        self, observer: Observer, group_name: str, activity: GroupActivity
    ) -> Group:
        """
        Adds a new group, then adds the observer
        to it
        """
        if observer.group:
            self.leave_group(observer)

        new_group = Group(name=group_name, observers=[], activity=activity)
        self.groups.append(new_group)
        self.join_group(observer, group_name)
        return new_group

    def join_group(self, observer: Observer, group_name: str) -> Union[Group, None]:
        """
        Add an observer to a group
        """
        _group = self.get_group_by_name(group_name)
        if _group is None:
            return None

        if observer.group is _group:
            # already in the group!
            return _group

        self.leave_group(observer)
        _group.observers.append(observer)
        observer.group = _group
        _group.add_event(EventType.MESSAGE, (observer.name, "joined"))

        return _group

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
        group.add_event(EventType.MESSAGE, (observer.name, "left"))

        group.observers.remove(observer)
        observer.group = None
        if self.observer_count(group) == 0:
            self.groups.remove(group)

        return True

    def list_groups(self):
        """
        Returns a list of tuples with group names and
        observer count if count=True
        """
        _ret_list = []
        for group in self.groups:
            _ret_list.append(group.serialize())

        return _ret_list

    def list_observers(self):
        """
        Returns a list of tuples with observers
        and group names
        """
        _ret_list = []
        for observer in self.observers:
            _ret_list.append(observer.serialize())

        return _ret_list

    def remove_observer(self, observer: Observer):
        """
        Cleans up all observer records on disconnect
        """
        self.leave_group(observer)
        self.observers.remove(observer)


@dataclass
class Mark:
    position: Position
    obj_id: int
    name: str
    observer: Observer
