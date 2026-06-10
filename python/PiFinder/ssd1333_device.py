"""
SSD1333 OLED device driver for the luma.oled framework.

176 RGB x 176 dot matrix OLED/PLED Segment/Common Driver with Controller.
Based on the Solomon Systech SSD1333 datasheet Rev 1.1 (Mar 2018).

Command set reference (key differences from SSD1351):
- 176x176 resolution (vs 128x128)
- MUX ratio register 0xCA takes value 175 (0xAF)
- No GPIO command (0xB5)
- No Function Select command (0xAB)
- No Segment Low Voltage command (0xB4)
- No second unlock command (0xFD 0xB1)
- Pre-charge voltage 0xBB uses A[4:0]
- VCOMH 0xBE uses A[2:0]
- Built-in linear LUT command 0xB9
"""

from luma.oled.device.color import color_device


class ssd1333(color_device):
    """
    Serial interface to the 16-bit color (5-6-5 RGB) SSD1333 OLED display.

    On creation, an initialization sequence is pumped to the display to
    properly configure it. Further control commands can then be called to
    affect the brightness and other settings.

    :param serial_interface: The serial interface (usually a
        :py:class:`luma.core.interface.serial.spi` instance) to delegate
        sending data and commands through.
    :param width: The number of horizontal pixels (optional, defaults to 176).
    :type width: int
    :param height: The number of vertical pixels (optional, defaults to 176).
    :type height: int
    :param rotate: An integer value of 0 (default), 1, 2 or 3 only, where 0 is
        no rotation, 1 is rotate 90° clockwise, 2 is 180° rotation and 3
        represents 270° rotation.
    :type rotate: int
    :param framebuffer: Framebuffering strategy, currently instances of
        ``diff_to_previous`` or ``full_frame`` are only supported.
    :type framebuffer: str
    :param bgr: Set to ``True`` if device pixels are BGR order (rather than RGB).
    :type bgr: bool
    :param h_offset: Horizontal offset (in pixels) of screen to device memory
        (default: 0).
    :type h_offset: int
    :param v_offset: Vertical offset (in pixels) of screen to device memory
        (default: 0).
    :type v_offset: int
    """

    def __init__(self, serial_interface=None, width=176, height=176, rotate=0,
                 framebuffer=None, h_offset=0, v_offset=0,
                 bgr=False, **kwargs):
        # A[2] in remap register: 0=color sequence A-B-C, 1=swapped C-B-A
        self._color_order = 0x04 if bgr else 0x00

        if h_offset != 0 or v_offset != 0:
            def offset(bbox):
                left, top, right, bottom = bbox
                return (left + h_offset, top + v_offset,
                        right + h_offset, bottom + v_offset)
            self._apply_offsets = offset

        super(ssd1333, self).__init__(serial_interface, width, height,
                                      rotate, framebuffer, **kwargs)

    def _supported_dimensions(self):
        return [(176, 176)]

    def _init_sequence(self):
        self.command(0xFD, 0x12)                    # Unlock IC MCU interface
        self.command(0xAE)                          # Display OFF (sleep mode on)
        self.command(0xB3, 0xF1)                    # Front clock: osc freq max (0xF), divide by 2
        self.command(0xCA, 0xAF)                    # MUX ratio = 175 (176 lines)
        self.command(0x15, 0x00, self._w - 1)       # Set column address range
        self.command(0x75, 0x00, self._h - 1)       # Set row address range
        self.command(0xA0, 0x70 | self._color_order) # Remap: 65k color, COM split odd even,
                                                     #        COM scan reversed, color order
        self.command(0xA1, 0x00)                    # Display start line = 0
        self.command(0xA2, 0x00)                    # Display offset = 0
        self.command(0xB1, 0x32)                    # Phase 1 = 4 DCLKs, Phase 2 = 6 DCLKs
        self.command(0xBB, 0x17)                    # Pre-charge voltage = 0.40 x VCC
        self.command(0xBE, 0x05)                    # VCOMH = 0.82 x VCC
        self.command(0xC7, 0x0F)                    # Master contrast: no reduction (max)
        self.command(0xB6, 0x08)                    # Second pre-charge period = 8 DCLKs
        self.command(0xB9)                          # Use built-in linear LUT
        self.command(0xA6)                          # Normal display mode

    def _set_position(self, top, right, bottom, left):
        self.command(0x15, left, right - 1)         # Set column address
        self.command(0x75, top, bottom - 1)         # Set row address
        self.command(0x5C)                          # Write RAM command

    def contrast(self, level):
        """
        Switches the display contrast to the desired level, in the range
        0-255. Sets all three color channels (A, B, C) to the same level.

        :param level: Desired contrast level in the range of 0-255.
        :type level: int
        """
        assert 0 <= level <= 255
        self.command(0xC1, level, level, level)

    def master_brightness(self, level):
        """
        Sets the master contrast current control (0xC7), a global brightness
        multiplier applied on top of the per-channel contrast set by
        :func:`contrast`. Effective current is scaled by (level + 1) / 16.

        :param level: Desired master brightness in the range 0-15.
            0 = 1/16 brightness (dimmest), 15 = full brightness (no reduction).
        :type level: int
        """
        assert 0 <= level <= 15
        self.command(0xC7, level)

    def command(self, cmd, *args):
        """
        Sends a command and an (optional) sequence of arguments through to the
        delegated serial interface. The SSD1333 uses the D/C# pin to distinguish
        commands (D/C#=LOW) from data arguments (D/C#=HIGH).
        """
        self._serial_interface.command(cmd)
        if len(args) > 0:
            self._serial_interface.data(list(args))
