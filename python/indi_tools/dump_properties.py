# for logging
import sys
import time
import logging

# import the PyIndi module
import PyIndi


# The IndiClient class which inherits from the module PyIndi.BaseClient class
# Note that all INDI constants are accessible from the module as PyIndi.CONSTANTNAME
class IndiClient(PyIndi.BaseClient):
    def __init__(self):
        super(IndiClient, self).__init__()
        self.logger = logging.getLogger("IndiClient")
        self.logger.info("creating an instance of IndiClient")

    def newDevice(self, d):
        """Emmited when a new device is created from INDI server."""
        self.logger.info(f"new device {d.getDeviceName()}")

    def removeDevice(self, d):
        """Emmited when a device is deleted from INDI server."""
        self.logger.info(f"remove device {d.getDeviceName()}")

    def newProperty(self, p):
        """Emmited when a new property is created for an INDI driver."""
        self.logger.info(
            f"new property {p.getName()} as {p.getTypeAsString()} for device {p.getDeviceName()}"
        )

    def updateProperty(self, p):
        """Emmited when a new property value arrives from INDI server."""
        self.logger.info(
            f"update property {p.getName()} as {p.getTypeAsString()} for device {p.getDeviceName()}"
        )

    def removeProperty(self, p):
        """Emmited when a property is deleted for an INDI driver."""
        self.logger.info(
            f"remove property {p.getName()} as {p.getTypeAsString()} for device {p.getDeviceName()}"
        )

    def newMessage(self, d, m):
        """Emmited when a new message arrives from INDI server."""
        self.logger.info(f"new Message {d.messageQueue(m)}")

    def serverConnected(self):
        """Emmited when the server is connected."""
        self.logger.info(f"Server connected ({self.getHost()}:{self.getPort()})")

    def serverDisconnected(self, code):
        """Emmited when the server gets disconnected."""
        self.logger.info(
            f"Server disconnected (exit code = {code},{self.getHost()}:{self.getPort()})"
        )


logging.basicConfig(format="%(asctime)s %(message)s", level=logging.INFO)

# Create an instance of the IndiClient class and initialize its host/port members
indiClient = IndiClient()
indiClient.setServer("localhost", 7624)

# Connect to server
print("Connecting and waiting 1 sec")
if not indiClient.connectServer():
    print(
        f"No indiserver running on {indiClient.getHost()}:{indiClient.getPort()} - Try to run"
    )
    print("  indiserver indi_simulator_telescope indi_simulator_ccd")
    sys.exit(1)

# Waiting for discover devices
time.sleep(1)

# Print list of devices. The list is obtained from the wrapper function getDevices as indiClient is an instance
# of PyIndi.BaseClient and the original C++ array is mapped to a Python List. Each device in this list is an
# instance of PyIndi.BaseDevice, so we use getDeviceName to print its actual name.
print("List of devices")
deviceList = indiClient.getDevices()
for device in deviceList:
    print(f"   > {device.getDeviceName()}")

# Print all properties and their associated values.
print("List of Device Properties")
for device in deviceList:
    print(f"-- {device.getDeviceName()}")
    genericPropertyList = device.getProperties()

    for genericProperty in genericPropertyList:
        print(f"   > {genericProperty.getName()} {genericProperty.getTypeAsString()}")

        if genericProperty.getType() == PyIndi.INDI_TEXT:
            for widget in PyIndi.PropertyText(genericProperty):
                print(
                    f"       {widget.getName()}({widget.getLabel()}) = {widget.getText()}"
                )

        if genericProperty.getType() == PyIndi.INDI_NUMBER:
            for widget in PyIndi.PropertyNumber(genericProperty):
                print(
                    f"       {widget.getName()}({widget.getLabel()}) = {widget.getValue()}"
                )

        if genericProperty.getType() == PyIndi.INDI_SWITCH:
            for widget in PyIndi.PropertySwitch(genericProperty):
                print(
                    f"       {widget.getName()}({widget.getLabel()}) = {widget.getStateAsString()}"
                )

        if genericProperty.getType() == PyIndi.INDI_LIGHT:
            for widget in PyIndi.PropertyLight(genericProperty):
                print(
                    f"       {widget.getLabel()}({widget.getLabel()}) = {widget.getStateAsString()}"
                )

        if genericProperty.getType() == PyIndi.INDI_BLOB:
            for widget in PyIndi.PropertyBlob(genericProperty):
                print(
                    f"       {widget.getName()}({widget.getLabel()}) = <blob {widget.getSize()} bytes>"
                )

# Disconnect from the indiserver
print("Disconnecting")
indiClient.disconnectServer()
