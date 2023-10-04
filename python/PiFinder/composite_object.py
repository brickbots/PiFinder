# CompositeObject class


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
            return self._data[name]
        except KeyError:
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            )

    def __str__(self):
        return f"CompositeObject: {str(self._data)}"

    def __repr__(self):
        return f"CompositeObject: {self.catalog_code} {self.sequence}"
