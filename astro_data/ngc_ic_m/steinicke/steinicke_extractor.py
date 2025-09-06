import pandas as pd
import json
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any
import os

@dataclass
class AstronomicalObject:
    """Class representing an astronomical object from NGC/IC catalog."""
    catalogue_prefix: str  # N (NGC) or I (IC)
    catalogue_number: int  # NI
    extension_letter: Optional[str] = None  # A
    component: Optional[int] = None  # C
    is_dreyer_object: bool = False  # D
    status: Optional[str] = None  # S
    high_precision: bool = False  # P
    constellation: Optional[str] = None  # CON
    right_ascension: Optional[Dict[str, int]] = None  # RH, RM, RS
    declination: Optional[Dict[str, Any]] = None  # V, DG, DM, DS
    blue_magnitude: Optional[float] = None  # Bmag
    visual_magnitude: Optional[float] = None  # Vmag
    color_index: Optional[float] = None  # B-V
    surface_brightness: Optional[float] = None  # SB
    diameter_larger: Optional[float] = None  # X
    diameter_smaller: Optional[float] = None  # Y
    position_angle: Optional[float] = None  # PA
    object_type: Optional[str] = None  # Type
    redshift: Optional[float] = None  # z
    redshift_distance: Optional[float] = None  # D(z)
    metric_distance: Optional[float] = None  # Dist
    pgc_number: Optional[int] = None  # PGC
    remarks: Optional[List[str]] = None  # All non-empty ID1-ID11 fields

    def to_dict(self) -> Dict[str, Any]:
        """Convert the object to a dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AstronomicalObject':
        """Create an object from a dictionary."""
        return cls(**data)


class AstronomyCatalog:
    """Class to manage a collection of astronomical objects."""

    def __init__(self):
        self.objects: List[AstronomicalObject] = []

    def add_object(self, obj: AstronomicalObject) -> None:
        """Add an astronomical object to the catalog."""
        self.objects.append(obj)

    def to_json(self, filepath: str) -> None:
        """Save the catalog to a JSON file."""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump([obj.to_dict() for obj in self.objects], f, indent=2)

    @classmethod
    def from_json(cls, filepath: str) -> 'AstronomyCatalog':
        """Load a catalog from a JSON file."""
        catalog = cls()
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            for item in data:
                catalog.add_object(AstronomicalObject.from_dict(item))
        return catalog

    def __len__(self) -> int:
        """Return the number of objects in the catalog."""
        return len(self.objects)

    def filter_by_type(self, object_type: str) -> List[AstronomicalObject]:
        """Filter objects by their type."""
        return [obj for obj in self.objects if obj.object_type == object_type]

    def filter_by_constellation(self, constellation: str) -> List[AstronomicalObject]:
        """Filter objects by their constellation."""
        return [obj for obj in self.objects if obj.constellation == constellation]

    def get_by_catalogue_id(self, prefix: str, number: int, extension: Optional[str] = None) -> Optional[AstronomicalObject]:
        """Get an object by its catalogue identifier."""
        for obj in self.objects:
            if (obj.catalogue_prefix == prefix and
                obj.catalogue_number == number and
                obj.extension_letter == extension):
                return obj
        return None


def extract_excel_data(excel_path: str) -> AstronomyCatalog:
    """
    Extract astronomical data from an Excel file into an AstronomyCatalog.

    Args:
        excel_path: Path to the Excel file

    Returns:
        An AstronomyCatalog containing the extracted data
    """
    try:
        # Read the Excel file
        df = pd.read_excel(excel_path)

        # Convert column names to uppercase to ensure consistent access
        df.columns = [col.strip().upper() for col in df.columns]

        # Create a new catalog
        catalog = AstronomyCatalog()

        # Process each row
        for idx, row in df.iterrows():
            try:
                # Extract all non-empty ID fields as remarks
                id_columns = [f"ID{i}" for i in range(1, 12) if f"ID{i}" in df.columns]
                remarks = [str(row[col]) for col in id_columns if pd.notna(row.get(col, pd.NA))]
                # If there are no remarks, set to None instead of empty list
                if not remarks:
                    remarks = None

                # Parse right ascension
                ra = {}
                if "RH" in df.columns and pd.notna(row.get("RH", pd.NA)):
                    ra["hours"] = int(row["RH"])
                if "RM" in df.columns and pd.notna(row.get("RM", pd.NA)):
                    ra["minutes"] = int(row["RM"])
                if "RS" in df.columns and pd.notna(row.get("RS", pd.NA)):
                    ra["seconds"] = float(row["RS"])

                # Parse declination - V is a string with "+" or "-"
                dec = {}
                if "V" in df.columns and pd.notna(row.get("V", pd.NA)):
                    # Check if V is "+" or "-" to determine sign
                    v_value = str(row["V"]).strip()
                    dec["sign"] = 1 if v_value == "+" else -1
                if "DG" in df.columns and pd.notna(row.get("DG", pd.NA)):
                    dec["degrees"] = abs(int(row["DG"]))
                if "DM" in df.columns and pd.notna(row.get("DM", pd.NA)):
                    dec["minutes"] = int(row["DM"])
                if "DS" in df.columns and pd.notna(row.get("DS", pd.NA)):
                    dec["seconds"] = float(row["DS"])

                # Create an astronomical object
                obj = AstronomicalObject(
                    catalogue_prefix=row.get("N", ""),
                    catalogue_number=int(row["NI"]) if pd.notna(row.get("NI", pd.NA)) else 0,
                    extension_letter=row.get("A", None) if pd.notna(row.get("A", pd.NA)) else None,
                    component=int(row["C"]) if pd.notna(row.get("C", pd.NA)) else None,
                    is_dreyer_object=row.get("D", "") == "*",
                    status=str(row["S"]) if pd.notna(row.get("S", pd.NA)) else None,
                    high_precision=row.get("P", "") == "*",
                    constellation=row.get("CON", None) if pd.notna(row.get("CON", pd.NA)) else None,
                    right_ascension=ra if ra else None,
                    declination=dec if dec else None,
                    blue_magnitude=float(row["BMAG"]) if pd.notna(row.get("BMAG", pd.NA)) else None,
                    visual_magnitude=float(row["VMAG"]) if pd.notna(row.get("VMAG", pd.NA)) else None,
                    color_index=float(row["B-V"]) if pd.notna(row.get("B-V", pd.NA)) else None,
                    surface_brightness=float(row["SB"]) if pd.notna(row.get("SB", pd.NA)) else None,
                    diameter_larger=float(row["X"]) if pd.notna(row.get("X", pd.NA)) else None,
                    diameter_smaller=float(row["Y"]) if pd.notna(row.get("Y", pd.NA)) else None,
                    position_angle=float(row["PA"]) if pd.notna(row.get("PA", pd.NA)) else None,
                    object_type=row.get("TYPE", None) if pd.notna(row.get("TYPE", pd.NA)) else None,
                    redshift=float(row["Z"]) if pd.notna(row.get("Z", pd.NA)) else None,
                    redshift_distance=float(row["D(Z)"]) if pd.notna(row.get("D(Z)", pd.NA)) else None,
                    metric_distance=float(row["DIST"]) if pd.notna(row.get("DIST", pd.NA)) else None,
                    pgc_number=int(row["PGC"]) if pd.notna(row.get("PGC", pd.NA)) else None,
                    remarks=remarks
                )

                catalog.add_object(obj)
            except Exception as e:
                print(f"Error processing row {idx}: {e}")
                continue

        return catalog
    except Exception as e:
        print(f"Error reading Excel file: {e}")
        return AstronomyCatalog()


def process_xls_to_json(excel_path: str, output_path: str) -> int:
    """
    Process an Excel file and save the result as JSON.
    
    Args:
        excel_path: Path to the input Excel file
        output_path: Path to save the output JSON file
        
    Returns:
        int: Number of objects processed
        
    Raises:
        FileNotFoundError: If the Excel file doesn't exist
        Exception: If processing fails
    """
    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Excel file not found: {excel_path}")
    
    # Extract data from Excel
    catalog = extract_excel_data(excel_path)
    
    # Save to JSON
    catalog.to_json(output_path)
    
    return len(catalog)


def main():
    """Main function to demonstrate usage."""
    # Define file paths
    excel_file = "NI2023.xls"
    json_output = "steinicke_catalog.json"

    # Check if the Excel file exists
    if not os.path.exists(excel_file):
        print(f"Error: Excel file '{excel_file}' not found.")
        return

    # Extract data from Excel
    print(f"Extracting data from '{excel_file}'...")
    catalog = extract_excel_data(excel_file)

    # Print some basic statistics
    print(f"Successfully processed {len(catalog)} astronomical objects")

    # Count objects by type
    type_count = {}
    for obj in catalog.objects:
        if obj.object_type:
            type_count[obj.object_type] = type_count.get(obj.object_type, 0) + 1

    # Display the top 5 most common object types
    if type_count:
        print("\nTop 5 most common object types:")
        sorted_types = sorted(type_count.items(), key=lambda x: x[1], reverse=True)
        for t, count in sorted_types[:5]:
            print(f"  {t}: {count} objects")

    # Save to JSON
    catalog.to_json(json_output)
    print(f"Data successfully extracted and saved to '{json_output}'")

    # Demonstrate loading from JSON
    loaded_catalog = AstronomyCatalog.from_json(json_output)
    print(f"Successfully loaded {len(loaded_catalog)} objects from JSON")


if __name__ == "__main__":
    main()
