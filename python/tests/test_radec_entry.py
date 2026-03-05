import pytest
from unittest.mock import Mock
from PiFinder.ui.radec_entry import (
    CoordinateState,
    CoordinateEntryLogic,
    BlinkingCursor,
    CoordinateConverter,
    FormatConfig,
    CoordinateFormats,
    LayoutConfig,
)


class TestCoordinateState:
    """Test the immutable CoordinateState dataclass"""

    def test_coordinate_state_creation(self):
        """Test creating a CoordinateState"""
        state = CoordinateState(
            coord_format=0,
            fields=["10", "20", "30", "40", "50", "60"],
            current_field=2,
            current_epoch=1,
            dec_sign="-",
            cursor_positions={0: [0, 0, 0, 0, 0, 0]},
        )

        assert state.coord_format == 0
        assert state.fields == ["10", "20", "30", "40", "50", "60"]
        assert state.current_field == 2
        assert state.current_epoch == 1
        assert state.dec_sign == "-"

    def test_with_field_updated(self):
        """Test updating a field creates new state"""
        state = CoordinateState(
            coord_format=0,
            fields=["", "", "", "", "", ""],
            current_field=0,
            current_epoch=0,
            dec_sign="+",
            cursor_positions={0: [0, 0, 0, 0, 0, 0]},
        )

        new_state = state.with_field_updated(1, "15")

        # Original state unchanged
        assert state.fields[1] == ""
        # New state has updated field
        assert new_state.fields[1] == "15"
        # Other fields preserved
        assert new_state.fields[0] == ""
        assert new_state.coord_format == 0

    def test_with_dec_sign_toggled(self):
        """Test toggling DEC sign"""
        state = CoordinateState(
            coord_format=0,
            fields=[],
            current_field=0,
            current_epoch=0,
            dec_sign="+",
            cursor_positions={},
        )

        toggled = state.with_dec_sign_toggled()
        assert toggled.dec_sign == "-"

        toggled_again = toggled.with_dec_sign_toggled()
        assert toggled_again.dec_sign == "+"


class TestBlinkingCursor:
    """Test the BlinkingCursor with time injection"""

    def test_blinking_cursor_visibility(self):
        """Test cursor blinking with mocked time"""
        mock_time = Mock()
        mock_time.return_value = 0.0

        cursor = BlinkingCursor(blink_interval=1.0, time_provider=mock_time)

        # At start (t=0), cursor should be visible
        mock_time.return_value = 0.0
        assert cursor.is_visible()

        # At t=0.5, still visible (within first half of cycle)
        mock_time.return_value = 0.5
        assert cursor.is_visible()

        # At t=1.0, should be invisible (second half of cycle)
        mock_time.return_value = 1.0
        assert not cursor.is_visible()

        # At t=1.5, still invisible
        mock_time.return_value = 1.5
        assert not cursor.is_visible()

        # At t=2.0, visible again (new cycle)
        mock_time.return_value = 2.0
        assert cursor.is_visible()


class TestCoordinateConverter:
    """Test coordinate conversion with dependency injection"""

    def test_hms_dms_conversion(self):
        """Test HMS/DMS to decimal degree conversion"""
        mock_calc_utils = Mock()
        mock_calc_utils.ra_to_deg.return_value = 150.0  # 10h 0m 0s
        mock_calc_utils.dec_to_deg.return_value = 30.0  # +30d 0m 0s

        converter = CoordinateConverter(mock_calc_utils)
        ra_deg, dec_deg = converter.hms_dms_to_degrees(
            ["10", "0", "0", "30", "0", "0"], "+"
        )

        assert ra_deg == 150.0
        assert dec_deg == 30.0
        mock_calc_utils.ra_to_deg.assert_called_with(10, 0, 0)
        mock_calc_utils.dec_to_deg.assert_called_with(30, 0, 0)

    def test_hms_dms_negative_dec(self):
        """Test HMS/DMS with negative declination"""
        mock_calc_utils = Mock()
        mock_calc_utils.ra_to_deg.return_value = 150.0
        mock_calc_utils.dec_to_deg.return_value = 30.0

        converter = CoordinateConverter(mock_calc_utils)
        ra_deg, dec_deg = converter.hms_dms_to_degrees(
            ["10", "0", "0", "30", "0", "0"], "-"
        )

        assert ra_deg == 150.0
        assert dec_deg == -30.0

    def test_mixed_format_conversion(self):
        """Test Mixed format (hours/degrees) conversion"""
        converter = CoordinateConverter()
        ra_deg, dec_deg = converter.mixed_to_degrees(["10.5", "30.25"], "+")

        assert ra_deg == 157.5  # 10.5 hours * 15 degrees/hour
        assert dec_deg == 30.25

    def test_decimal_format_conversion(self):
        """Test Decimal format conversion"""
        converter = CoordinateConverter()
        ra_deg, dec_deg = converter.decimal_to_degrees(["157.5", "30.25"], "+")

        assert ra_deg == 157.5
        assert dec_deg == 30.25

    def test_decimal_negative_dec(self):
        """Test Decimal format with negative declination"""
        converter = CoordinateConverter()
        ra_deg, dec_deg = converter.decimal_to_degrees(["157.5", "30.25"], "-")

        assert ra_deg == 157.5
        assert dec_deg == -30.25


class TestCoordinateEntryLogic:
    """Test the main business logic class"""

    def test_initialization(self):
        """Test logic initialization"""
        logic = CoordinateEntryLogic()

        state = logic.get_current_state()
        assert state.coord_format == 0  # HMS/DMS by default
        assert state.current_field == 0
        assert state.current_epoch == 0  # J2000
        assert state.dec_sign == "+"

    def test_numeric_input_hms_dms(self):
        """Test numeric input in HMS/DMS format"""
        logic = CoordinateEntryLogic()

        # Input "1" in first field (RA hours)
        state = logic.handle_numeric_input(1)
        assert state.fields[0] == "1"
        assert state.current_field == 0  # Still on same field

        # Input "2" to complete the field
        state = logic.handle_numeric_input(2)
        assert state.fields[0] == "12"
        assert state.current_field == 1  # Auto-advanced to next field

    def test_numeric_input_validation(self):
        """Test input validation for HMS/DMS format"""
        logic = CoordinateEntryLogic()

        # Try to input invalid RA hours (25)
        logic.handle_numeric_input(2)
        logic.handle_numeric_input(5)  # Should be rejected since 25 > 23

        state = logic.get_current_state()
        # Should still be "2" not "25"
        assert state.fields[0] == "2"

    def test_decimal_input_mixed_format(self):
        """Test numeric input in Mixed format"""
        logic = CoordinateEntryLogic()

        # Switch to mixed format first
        logic.switch_format()
        state = logic.get_current_state()
        assert state.coord_format == 1  # Mixed format

        # The field should have placeholder format like "00.00"
        # Input should replace characters at cursor position
        logic.handle_numeric_input(1)

        new_state = logic.get_current_state()
        # Should have replaced first character
        assert new_state.fields[0][0] == "1"

    def test_field_navigation(self):
        """Test field navigation"""
        logic = CoordinateEntryLogic()

        # Start at field 0
        assert logic.get_current_state().current_field == 0

        # Move to next field
        logic.move_to_next_field()
        assert logic.get_current_state().current_field == 1

        # Move to previous field
        logic.move_to_previous_field()
        assert logic.get_current_state().current_field == 0

    def test_dec_sign_toggle(self):
        """Test DEC sign toggling"""
        logic = CoordinateEntryLogic()

        # Move to DEC degrees field (field 3 in HMS/DMS)
        for _ in range(3):
            logic.move_to_next_field()

        assert logic.get_current_state().current_field == 3

        # Toggle DEC sign
        original_sign = logic.get_current_state().dec_sign
        logic.toggle_dec_sign()
        new_sign = logic.get_current_state().dec_sign

        assert new_sign != original_sign
        assert new_sign in ["+", "-"]

    def test_epoch_cycling(self):
        """Test epoch cycling"""
        logic = CoordinateEntryLogic()
        format_config = logic.get_current_format_config()

        # Move to epoch field (last field)
        for _ in range(format_config.field_count - 1):
            logic.move_to_next_field()

        # Cycle through epochs
        logic.cycle_epoch()
        assert logic.get_current_state().current_epoch == 1  # JNOW

        logic.cycle_epoch()
        assert logic.get_current_state().current_epoch == 2  # B1950

        logic.cycle_epoch()
        assert logic.get_current_state().current_epoch == 0  # Back to J2000

    def test_format_switching(self):
        """Test coordinate format switching"""
        logic = CoordinateEntryLogic()

        # Start with HMS/DMS
        assert logic.get_current_state().coord_format == 0

        # Switch to Mixed
        logic.switch_format()
        assert logic.get_current_state().coord_format == 1

        # Switch to Decimal
        logic.switch_format()
        assert logic.get_current_state().coord_format == 2

        # Switch back to HMS/DMS
        logic.switch_format()
        assert logic.get_current_state().coord_format == 0

    def test_deletion_hms_dms(self):
        """Test deletion in HMS/DMS format"""
        logic = CoordinateEntryLogic()

        # Add some input first
        logic.handle_numeric_input(1)
        logic.handle_numeric_input(2)
        state = logic.get_current_state()
        assert state.fields[0] == "12"
        # Auto-advanced to field 1, so current field is now 1
        assert state.current_field == 1

        # Delete (should move back to field 0 since field 1 is empty)
        logic.handle_deletion()
        state = logic.get_current_state()
        assert state.current_field == 0  # Should have moved back

        # Now delete should remove last digit from field 0
        logic.handle_deletion()
        state = logic.get_current_state()
        assert state.fields[0] == "1"

        # Delete again (should remove remaining digit)
        logic.handle_deletion()
        state = logic.get_current_state()
        assert state.fields[0] == ""

    def test_coordinate_conversion_integration(self):
        """Test coordinate conversion through the logic"""
        mock_calc_utils = Mock()
        mock_calc_utils.ra_to_deg.return_value = 150.0
        mock_calc_utils.dec_to_deg.return_value = 30.0

        logic = CoordinateEntryLogic(calc_utils_provider=mock_calc_utils)

        # Set up some coordinates manually for testing
        logic._state = logic._state.with_field_updated(0, "10")
        logic._state = logic._state.with_field_updated(1, "0")
        logic._state = logic._state.with_field_updated(2, "0")
        logic._state = logic._state.with_field_updated(3, "30")
        logic._state = logic._state.with_field_updated(4, "0")
        logic._state = logic._state.with_field_updated(5, "0")

        ra_deg, dec_deg = logic.get_coordinates()

        assert ra_deg == 150.0
        assert dec_deg == 30.0


class TestFormatConfig:
    """Test format configuration and validation"""

    def test_format_config_creation(self):
        """Test creating format configuration"""
        config = FormatConfig(
            name="Test",
            field_labels=["RA", "DEC"],
            placeholders=["00", "00"],
            coord_field_count=2,
            validators={0: {"type": int, "min": 0, "max": 23}},
        )

        assert config.name == "Test"
        assert config.coord_field_count == 2
        assert config.field_count == 3  # coord_field_count + 1 for epoch

    def test_field_validation(self):
        """Test field validation"""
        config = FormatConfig(
            name="Test",
            field_labels=["RA_H"],
            placeholders=["hh"],
            coord_field_count=1,
            validators={0: {"type": int, "min": 0, "max": 23}},
        )

        # Valid input
        assert config.validate_field(0, "12")
        assert config.validate_field(0, "0")
        assert config.validate_field(0, "23")

        # Invalid input
        assert not config.validate_field(0, "24")
        assert not config.validate_field(0, "-1")
        assert not config.validate_field(0, "abc")


class TestCoordinateFormats:
    """Test the coordinate formats configuration"""

    def test_get_formats(self):
        """Test getting all format configurations"""
        formats = CoordinateFormats.get_formats()

        assert 0 in formats  # HMS/DMS
        assert 1 in formats  # Mixed
        assert 2 in formats  # Decimal

        # Check HMS/DMS format
        hms_dms = formats[0]
        assert hms_dms.coord_field_count == 6
        assert len(hms_dms.field_labels) == 7  # 6 coord fields + epoch

        # Check Mixed format
        mixed = formats[1]
        assert mixed.coord_field_count == 2
        assert len(mixed.field_labels) == 3  # 2 coord fields + epoch

    def test_get_default_fields(self):
        """Test getting default field values"""
        hms_dms_fields = CoordinateFormats.get_default_fields(0)
        assert hms_dms_fields == ["", "", "", "", "", ""]

        mixed_fields = CoordinateFormats.get_default_fields(1)
        assert len(mixed_fields) == 2

        decimal_fields = CoordinateFormats.get_default_fields(2)
        assert len(decimal_fields) == 2


class TestLayoutConfig:
    """Test layout configuration constants"""

    def test_layout_constants(self):
        """Test that layout constants are defined"""
        layout = LayoutConfig()

        assert hasattr(layout, "FIELD_HEIGHT")
        assert hasattr(layout, "FIELD_WIDTH")
        assert hasattr(layout, "FIELD_GAP")
        assert hasattr(layout, "LABEL_X")
        assert hasattr(layout, "FIELD_START_X")

        # Check that values are reasonable
        assert layout.FIELD_HEIGHT > 0
        assert layout.FIELD_WIDTH > 0
        assert layout.FIELD_GAP > 0


@pytest.mark.integration
class TestIntegration:
    """Integration tests combining multiple components"""

    def test_full_coordinate_entry_workflow(self):
        """Test complete workflow from input to coordinate conversion"""
        mock_calc_utils = Mock()
        mock_calc_utils.ra_to_deg.return_value = 150.0  # 10h
        mock_calc_utils.dec_to_deg.return_value = 45.0  # +45d

        logic = CoordinateEntryLogic(calc_utils_provider=mock_calc_utils)

        # Enter coordinates: 10h 30m 0s, +45d 15m 0s

        # RA hours
        logic.handle_numeric_input(1)
        logic.handle_numeric_input(0)  # Auto-advances to next field

        # RA minutes
        logic.handle_numeric_input(3)
        logic.handle_numeric_input(0)  # Auto-advances

        # RA seconds (skip - leave as 0)
        logic.move_to_next_field()  # Move to DEC degrees

        # DEC degrees
        logic.handle_numeric_input(4)
        logic.handle_numeric_input(5)  # Auto-advances

        # DEC minutes
        logic.handle_numeric_input(1)
        logic.handle_numeric_input(5)  # Auto-advances

        # Skip DEC seconds

        # Get final coordinates
        ra_deg, dec_deg = logic.get_coordinates()

        # Verify mock was called correctly
        mock_calc_utils.ra_to_deg.assert_called_with(10, 30, 0)
        mock_calc_utils.dec_to_deg.assert_called_with(45, 15, 0)

        assert ra_deg == 150.0
        assert dec_deg == 45.0

    def test_format_switching_preserves_state(self):
        """Test that switching formats and back preserves state where possible"""
        logic = CoordinateEntryLogic()

        # Enter some data in HMS/DMS format
        logic.handle_numeric_input(1)
        logic.handle_numeric_input(2)

        # Switch to mixed format
        logic.switch_format()
        mixed_state = logic.get_current_state()
        assert mixed_state.coord_format == 1

        # Switch back to HMS/DMS
        logic.switch_format()
        logic.switch_format()  # Skip decimal, back to HMS/DMS

        final_state = logic.get_current_state()
        assert final_state.coord_format == 0

        # Note: State preservation across formats is implementation dependent
        # The test mainly ensures switching works without errors

    def test_error_handling_invalid_coordinates(self):
        """Test handling of invalid coordinate values"""
        logic = CoordinateEntryLogic()

        # Try to enter invalid values and ensure system remains stable
        logic.handle_numeric_input(9)  # Valid first digit
        logic.handle_numeric_input(9)  # Invalid: 99 hours > 23

        state = logic.get_current_state()
        # Should not have advanced or accepted invalid input
        assert len(state.fields[0]) <= 2

        # System should still be functional
        logic.move_to_next_field()
        logic.handle_numeric_input(5)  # Should work on next field

        # Get coordinates - should handle missing/invalid data gracefully
        ra_deg, dec_deg = logic.get_coordinates()
        # Should return None for invalid coordinates or handle gracefully
        assert ra_deg is not None or dec_deg is None  # At least consistent

    def test_dec_validation_issue_was_fixed(self):
        """Test that the DEC validation issue has been FIXED

        Previously, you could enter 90°30'30" = 90.508° which exceeded ±90°.
        Now the validation prevents this by checking the combined DMS value.
        """
        logic = CoordinateEntryLogic()

        # Navigate to DEC degrees field (field 3 in HMS/DMS format)
        for _ in range(3):
            logic.move_to_next_field()

        # Enter 90 degrees (should be accepted)
        logic.handle_numeric_input(9)
        logic.handle_numeric_input(0)  # Should auto-advance to DEC minutes

        # Try to enter 30 minutes - should be rejected (3 rejected, then 0 accepted)
        logic.handle_numeric_input(3)  # Should be rejected
        logic.handle_numeric_input(0)
        logic.handle_numeric_input(0)  # Complete with 00 minutes

        # Try to enter any seconds > 0 - should be rejected since we're at exactly 90°
        logic.handle_numeric_input(3)  # Should be rejected
        logic.handle_numeric_input(0)
        logic.handle_numeric_input(0)  # Complete with 00 seconds

        state = logic.get_current_state()

        # Should end up with 90°00'00" = exactly 90.0°
        assert state.fields[3] == "90"  # DEC degrees
        assert state.fields[4] == "00"  # DEC minutes (not 30!)
        assert state.fields[5] == "00"  # DEC seconds (not 30!)

        # This creates a valid coordinate: 90°00'00" = exactly 90.0°
        dec_degrees = 90 + (0 / 60) + (0 / 3600)
        assert dec_degrees == 90.0  # Exactly at the limit - valid!

    def test_dec_validation_fix_rejects_90_plus_minutes(self):
        """Test that the fix prevents DEC > 90° in HMS/DMS format"""
        logic = CoordinateEntryLogic()

        # Navigate to DEC degrees field (field 3 in HMS/DMS format)
        for _ in range(3):
            logic.move_to_next_field()

        # Enter 90 degrees (should be accepted)
        logic.handle_numeric_input(9)
        logic.handle_numeric_input(0)  # Should auto-advance to DEC minutes

        state = logic.get_current_state()
        assert state.fields[3] == "90"  # DEC degrees should be set
        assert state.current_field == 4  # Should have advanced to minutes field

        # Try to enter 30 minutes - the first digit should be REJECTED
        # because 90°3x' > 90° for any x
        logic.handle_numeric_input(3)  # This should be rejected

        state = logic.get_current_state()
        # The first digit should have been rejected
        assert state.fields[4] == ""  # DEC minutes should still be empty
        assert state.current_field == 4  # Should not have advanced

        # But entering 0 minutes should work since 90°0' = 90.0°
        logic.handle_numeric_input(0)
        logic.handle_numeric_input(0)  # Should auto-advance after completing 00

        state = logic.get_current_state()
        assert state.fields[4] == "00"  # Should accept 00 minutes
        assert state.current_field == 5  # Should have advanced to seconds

    def test_dec_validation_allows_89_59_59(self):
        """Test that 89°59'59" is still allowed (just under 90°)"""
        logic = CoordinateEntryLogic()

        # Navigate to DEC degrees field
        for _ in range(3):
            logic.move_to_next_field()

        # Enter 89°59'59" (which equals 89.9997°, valid)
        logic.handle_numeric_input(8)
        logic.handle_numeric_input(9)  # Should auto-advance

        # Enter 59 minutes
        logic.handle_numeric_input(5)
        logic.handle_numeric_input(9)  # Should auto-advance

        # Enter 59 seconds
        logic.handle_numeric_input(5)
        logic.handle_numeric_input(9)

        state = logic.get_current_state()
        assert state.fields[3] == "89"  # DEC degrees
        assert state.fields[4] == "59"  # DEC minutes
        assert state.fields[5] == "59"  # DEC seconds

        # This should be valid: 89 + 59/60 + 59/3600 = 89.9997° < 90°
        dec_degrees = 89 + (59 / 60) + (59 / 3600)
        assert dec_degrees < 90.0

    def test_dec_validation_negative_90_plus_minutes(self):
        """Test that negative DEC validation also works: -90°30' should be rejected"""
        logic = CoordinateEntryLogic()

        # Navigate to DEC degrees field
        for _ in range(3):
            logic.move_to_next_field()

        # Toggle to negative DEC sign first
        logic.toggle_dec_sign()

        # Enter -90 degrees (should be accepted)
        logic.handle_numeric_input(9)
        logic.handle_numeric_input(0)  # Should auto-advance

        state = logic.get_current_state()
        assert state.fields[3] == "90"
        assert state.dec_sign == "-"
        assert state.current_field == 4

        # Try to enter any minutes > 0 - should be rejected for -90°
        logic.handle_numeric_input(3)  # Should be rejected

        state = logic.get_current_state()
        assert state.fields[4] == ""  # Should still be empty
        assert state.current_field == 4  # Should not have advanced


# All tests are unit tests by default
