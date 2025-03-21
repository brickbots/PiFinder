from dataclasses import dataclass
from dataclasses_json import dataclass_json
from typing import Union


@dataclass
class Location:
    name: str
    latitude: float
    longitude: float
    height: float
    error_in_m: float
    source: str
    is_default: bool = False

    def __str__(self):
        return f"{self.name} ({self.latitude:.4f}°, {self.longitude:.4f}°)"


@dataclass_json
@dataclass
class Locations:
    locations: list[Location]

    @property
    def default_location(self) -> Union[Location, None]:
        """Returns the default location or None if no default is set"""
        for location in self.locations:
            if location.is_default:
                return location
        return None

    def set_default(self, location: Location):
        """Sets the specified location as default, removing default status from any other location"""
        for loc in self.locations:
            loc.is_default = False
        location.is_default = True

    def add_location(self, location: Location):
        """Add a new location to the list"""
        self.locations.append(location)
        # If this is the first location, make it default
        if len(self.locations) == 1:
            location.is_default = True

    def remove_location(self, location: Location):
        """Remove a location from the list"""
        if location in self.locations:
            was_default = location.is_default
            self.locations.remove(location)
            
            # Update default if needed
            if was_default and self.locations:
                self.locations[0].is_default = True 