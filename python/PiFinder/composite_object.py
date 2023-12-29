# CompositeObject class
from dataclasses import dataclass, field


@dataclass
class CompositeObject:
    """A catalog object, augmented with related DB data"""

    # id is the primary key of the catalog_objects table
    id: int = field(default=-1)
    # object_id is the primary key of the objects table
    object_id: int = field(default=-1)
    obj_type: str = field(default="")
    # ra in degrees, J2000
    ra: float = field(default=0.0)
    # dec in degrees, J2000
    dec: float = field(default=0.0)
    const: str = field(default="")
    size: str = field(default="")
    mag: str = field(default="")
    catalog_code: str = field(default="")
    # we want catalogs of M and NGC etc, so sequence should be a name like M 31
    # deduplicated from names. Catalog code stays, because this collection of
    # things has a name
    sequence: int = field(default=0)
    description: str = field(default="")
    names: list = field(default_factory=list)
    image_name: str = field(default="")
    logged: bool = field(default=False)

    @classmethod
    def from_dict(cls, d):
        return cls(**d)
