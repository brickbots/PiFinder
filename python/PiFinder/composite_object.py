# CompositeObject class
import logging


class CompositeObject:
    """
    Represents an object that is a combination of
    catalog data and the basic data from the objects table
    """

    def __init__(self, data_dict):
        self._data = data_dict

    def __getattr__(self, name):
        # Return the value if it exists in the dictionary.
        # If not, raise an AttributeError.
        try:
            if name in self._data:
                return self._data[name]
            else:
                logging.debug("CompositeObject: %s not found in %s", name, self._data)
        except KeyError:
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            )

    # getstate and setstate are needed because of the pickling that happens in the manager.
    # we should probably not use the manager for interthread communication
    def __getstate__(self):
        return self._data

    def __setstate__(self, state):
        self._data = state

    def __str__(self):
        return f"CompositeObject: {str(self._data)}"

    def __repr__(self):
        return f"CompositeObject: {self.catalog_code} {self.sequence}"
