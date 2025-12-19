"""
Helper to save sweep metadata during capture.
Add this to your sweep capture code.
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
import pytz

logger = logging.getLogger("SweepMetadata")


def save_sweep_metadata(
    sweep_dir: Path,
    observer_lat: float,
    observer_lon: float,
    observer_altitude_m: Optional[float] = None,
    gps_datetime: Optional[str] = None,
    reference_sqm: Optional[float] = None,
    ra_deg: Optional[float] = None,
    dec_deg: Optional[float] = None,
    altitude_deg: Optional[float] = None,
    azimuth_deg: Optional[float] = None,
    notes: str = "",
):
    """
    Save metadata file in sweep directory.

    Call this during sweep capture to save observation details.

    Args:
        sweep_dir: Path to sweep directory
        observer_lat: Observer latitude in degrees
        observer_lon: Observer longitude in degrees
        observer_altitude_m: Observer altitude in meters (optional)
        gps_datetime: GPS datetime as ISO string (optional)
        reference_sqm: Reference SQM value from external meter (optional)
        ra_deg: Right Ascension from solver (optional)
        dec_deg: Declination from solver (optional)
        altitude_deg: Altitude angle above horizon in degrees (optional)
        azimuth_deg: Azimuth angle in degrees (optional)
        notes: Any additional notes
    """
    metadata: Dict[str, Any] = {
        "timestamp": gps_datetime
        if gps_datetime
        else datetime.now(pytz.timezone("Europe/Brussels")).isoformat(),
        "observer": {
            "latitude_deg": observer_lat,
            "longitude_deg": observer_lon,
        },
        "sweep_directory": str(sweep_dir),
    }

    if observer_altitude_m is not None:
        metadata["observer"]["altitude_m"] = observer_altitude_m

    if reference_sqm is not None:
        metadata["reference_sqm"] = reference_sqm

    if ra_deg is not None and dec_deg is not None:
        metadata["coordinates"] = {
            "ra_deg": ra_deg,
            "dec_deg": dec_deg,
        }
        if altitude_deg is not None:
            metadata["coordinates"]["altitude_deg"] = altitude_deg
        if azimuth_deg is not None:
            metadata["coordinates"]["azimuth_deg"] = azimuth_deg

    if notes:
        metadata["notes"] = notes

    # Save to JSON file
    metadata_file = sweep_dir / "sweep_metadata.json"
    logger.info(f"Writing metadata to: {metadata_file}")

    try:
        with open(metadata_file, "w") as f:
            json.dump(metadata, f, indent=2)
        logger.info(f"Successfully saved metadata to {metadata_file}")
    except Exception as e:
        logger.error(f"Failed to write metadata file: {e}")
        raise

    return metadata_file


# Example usage - add this to your sweep capture code:
if __name__ == "__main__":
    from pathlib import Path

    # Example: Save metadata during sweep
    sweep_dir = Path("../test_images/sweep/sweep_20251116_132256_187sqm")

    save_sweep_metadata(
        sweep_dir=sweep_dir,
        observer_lat=50.8503,  # Brussels
        observer_lon=4.3517,
        reference_sqm=18.7,
        notes="Diaphragm fully open, clear sky",
    )
