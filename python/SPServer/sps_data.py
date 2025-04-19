#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
Dataclasses to support the StarParty Server
"""

from dataclasses import dataclass, field
from typing import Union


@dataclass
class Group:
    name: str
    marks: list["Mark"]

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


@dataclass
class Mark:
    position: Position
    obj_id: int
    name: str
    observer: Observer
