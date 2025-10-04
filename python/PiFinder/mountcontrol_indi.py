from PiFinder.mountcontrol_interface import MountControlBase
import PyIndi
import logging
import time

from PiFinder.multiproclogging import MultiprocLogging

logger = logging.getLogger("IndiMountControl")

# Implement or override methods as needed
class PiFinderIndiClient(PyIndi.BaseClient):
    """TODO Add class docstring."""
    def __init__(self):
        super().__init__()
        self.telescope_device = None

    def newDevice(self, device):
        # Called when a new device is detected

        # Check if the device is a typical telescope device
        device_name = device.getDeviceName().lower()
        if self.telescope_device is None and any(keyword in device_name for keyword in ["telescope", "mount", "eqmod", "lx200"]):
            self.telescope_device = device
            logger.info(f"Telescope device set: {device.getDeviceName()}")

    def removeDevice(self, device):
        # Called when a device is removed
        logger.info(f"Device removed: {device.getDeviceName()}")

    def newProperty(self, property):
        # Called when a new property is created
        print(f"New property: {property.getName()} on device {property.getDeviceName()}")

    def removeProperty(self, property):
        # Called when a property is deleted
        print(f"Property removed: {property.getName()} on device {property.getDeviceName()}")

    def newBLOB(self, bp):
        # Handle new BLOB property if needed
        pass

    def newSwitch(self, svp):
        # Handle new switch property value
        pass

    def newNumber(self, nvp):
        # Handle new number property value
        pass

    def newText(self, tvp):
        # Handle new text property value
        pass

    def newLight(self, lvp):
        # Handle new light property value
        pass

    def newMessage(self, device, message):
        # Handle new message from device
        print(f"Message from {device.getDeviceName()}: {message}")

    def serverConnected(self):
        print("Connected to INDI server.")

    def serverDisconnected(self, code):
        print(f"Disconnected from INDI server with code {code}.")


class MountControlIndi(MountControlBase):
    def __init__(self, target_queue, console_queue, shared_state, log_queue, verbose=False):
        super().__init__(target_queue, console_queue, shared_state, log_queue, verbose)

        # Connect to the INDI server
        self.client = PiFinderIndiClient()
        self.client.setServer("localhost", 7624)
        if not self.client.connectServer():
            logger.error("Failed to connect to INDI server at localhost:7624")
        else:
            logger.info("Connected to INDI server at localhost:7624")


def run(
    target_queue, console_queue, shared_state, log_queue, verbose=False
):
    MultiprocLogging.configurer(log_queue)
    mount_control = MountControlIndi(target_queue, console_queue, shared_state, log_queue, verbose)
    try:
        mount_control.run()
    except KeyboardInterrupt:
        logger.info("Shutting down MountControlIndi.")
        raise # don't swallow this, it is used to terminate the process



if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting MountControlIndi...")

    try:
        mount_control = MountControlIndi()
        logger.info("MountControlIndi started. Press Ctrl+C to exit.")
        while True:
            time.sleep(1)
            pass  # Keep the main thread alive
    except KeyboardInterrupt:
        logger.info("Shutting down MountControlIndi.")
        raise
    except Exception as e:
        logger.exception(f"Exception occurred: {e}")
