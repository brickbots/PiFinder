# PiFinder Mount Control

PiFinder now supports controlling computerized telescope mounts via the INDI protocol. This feature allows you to automatically slew your mount to celestial objects, sync mount positions with plate-solved coordinates, and perform manual adjustments - all directly from the PiFinder interface.

## Features

- **Automatic GoTo**: Send your mount to any object in the PiFinder catalog with a single keypress
- **Position Sync**: Synchronize your mount's position using PiFinder's plate-solved coordinates
- **Manual Movement**: (In development - not usable yet) Fine-tune mount positioning with directional controls (North, South, East, West)
- **Target Refinement**: Automatically refines target acquisition by syncing with plate-solved position after initial slew
- **Real-time Position Updates**: Mount position is continuously monitored and displayed
- **Drift Compensation**: (In development) Compensate for polar alignment errors during tracking

## Installation

### Prerequisites

- PiFinder device running on Raspberry Pi
- Compatible INDI-supported telescope mount
- A cable connection between PiFinder and mount
- PiFinder in client mode to install software

### Step 1: Check-out alpha version software of Indi Mount Control

The mount control feature is currently in alpha development. To use it, you need to check out the development branch.

**On a typical PiFinder installation:**

1. **Navigate to the PiFinder directory:**
   ```bash
   cd ~/PiFinder
   ```

2. **Stop the PiFinder service:**
   ```bash
   sudo systemctl stop pifinder
   ```

3. **Add the jscheidtmann fork as a remote** (if not already added):
   ```bash
   git remote add jscheidtmann https://github.com/jscheidtmann/PiFinder.git
   ```

   If the remote already exists, update it:
   ```bash
   git remote set-url jscheidtmann https://github.com/jscheidtmann/PiFinder.git
   ```

4. **Fetch the latest changes from the fork:**
   ```bash
   git fetch jscheidtmann
   ```

5. **Check out the mount control branch:**
   ```bash
   git checkout -b indi_mount_control jscheidtmann/indi_mount_control
   ```

   If you've already checked out this branch before, update it:
   ```bash
   git checkout indi_mount_control
   git pull jscheidtmann indi_mount_control
   ```

6. **Install requirements:**
   ```bash
   sudo pip install python/requirements.txt
   ```

**Note 1:** The pifinder service will be started later, as some indi specific requirements are not yet installed.

**Note 2:** The mount control code is under active development. Check the branch regularly for updates and bug fixes.

### Step 2: Run Installation Script for INDI

SSH to your PiFinder, login and execute the installation script from the PiFinder directory:

```bash
cd /home/pifinder/PiFinder
bash install-indi-pifinder.sh
```

This script will:
1. Update system packages
2. Install INDI library dependencies
3. Compile and install INDI from source (current version 2.1.6)
4. Install PyIndi client library
5. Install modified INDI Web Manager as a systemd service, that allows configuring the mount
6. Set up Chrony for GPS time synchronization

**Important Notes:**
- The installation process may take 30-60 minutes depending on your system
- The PiFinder service will be temporarily stopped during INDI compilation
- After installation completes, set your timezone using `sudo raspi-config`

### Step 2: Verify Installation

Check that INDI Web Manager is running:

```bash
systemctl status indiwebmanager.service
```

The service should show as "active (running)".

Navigate to "http://pifinder.local/8624" and the Indi Web Manager should display.

## Configuration

At best configuration is done after installation. If you're in the field and/or testing the PiFinder on a new mount, follow these instructions:

### Connect to your PiFinder using a cell phone, tablet or laptop

To access the INDI Web Manager and configure your mount, you need to connect to your PiFinder over WiFi. PiFinder supports two WiFi modes:

#### Access Point (AP) Mode (Default)

In AP mode, the PiFinder creates its own WiFi network for easy connection:

1. **Find the PiFinder network:**
   - Look for a WiFi network named **"PiFinderAP"**
   - This network has **no password** for easy field use

2. **Connect your device:**
   - Connect your phone, tablet, or laptop to the PiFinderAP network
   - Once connected, open a web browser

3. **Access the PiFinder:**
   - Navigate to `http://pifinder.local:8624` for INDI Web Manager
   - If that doesn't work, check the PiFinder's Status screen for its IP address
   - Use `http://<ip-address>:8624` instead

#### Client Mode

In Client mode, the PiFinder connects to your existing WiFi network:

1. **Connect to PiFinder** and navigate to `http://pifinder.local` or 

2. **Find the PiFinder's IP:**
   - Check your router's DHCP client list, or
   - Check the PiFinder's Status screen for its assigned IP

3. **Access the PiFinder:**
   - Navigate to `http://pifinder.local:8624` for INDI Web Manager
   - or use `http://<ip-address>:8624` instead

### Setting Up Mount Connection with INDI Web Manager

INDI Web Manager provides a web interface for managing INDI drivers and connecting to your mount.

1. **Access INDI Web Manager**
   - Navigate to `http://pifinder.local:8624` in a web browser, or use the name you've configured for your PiFinder.
   - If this doesn't work, lookup the PiFinder's IP and use: `http://<pifinder-ip>:8624`

2. **Start Your Mount Driver**
   - In the INDI Web Manager interface, create a new profile by entering a profile name in the "New Profile" entry box and clicking "+".
   - Then in the list of drivers locate the respective driver and click on it.
   - Common drivers include:
     - **iEQ**: For iOptron mounts
     - **EQMod**: For Synta/SkyWatcher EQ mounts via EQMOD cable
     - **LX200**: For Meade LX200 compatible mounts
     - **Celestron**: For Celestron computerized mounts
     - **Telescope Simulator**: For testing without hardware
   - Check both the "Auto Start" and "Auto Connect" boxes
   - Click on "Save ⭳" button next to the profile name.
   - Click on the "⚙️ Start" button to start the server and driver.
   - Once the driver comes up, it is listed in the list of connected drivers on left hand side.
   - If it does not display, then there's a problem starting that driver. 
   - Run `indiserver <name of driver>` from the command line to get a grip on the problem.
   
3. **Configure Driver Settings**
   - Click the listed driver name to open another webpage showing its properties. 
   - Set connection parameters (serial port, IP address, etc.) as needed for your mount
   - Click "Connect" to establish the connection to your physical mount
   - When the connection is established the list of properties and pages displayed should grow. 
   - If it doesn't connect, check the error message displayed at the bottom.

4. **Verify Connection**
   - Once connected, the driver status should show "Connected"
   - You should be able to start tracking or move the mount using the properties displayed on the web page.

### Start PiFinder service

Do not forget to start the pifinder service.
```bash
sudo systemctl start pifinder
```

Use

```bash
sudo systemctl status pifinder
```

To check it is up and running fine.

## Usage

### Object Details Screen

When viewing object details in PiFinder, mount control features are integrated directly into the interface. 
The mount control functionality works across all displays of the details display.

#### Display Modes

Press the **Square** button to cycle through display modes:

1. **LOCATE Mode** (Default): Shows pointing arrows to guide manual mount positioning
2. **POSS/SDSS Mode**: Shows DSS/SDSS images if available
3. **MOUNT CONTROL Mode**: Displays keyboard shortcuts for mount commands
4. **DESC Mode**: Displays object description and metadata

#### Mount Control Commands

Mount control commands work in **any display mode** by pressing number keys:

| Key | Command | Description |
|-----|---------|-------------|
| **0** | Stop Mount | Immediately stops all mount movement |
| **1** | Init Mount | Initialize mount connection and sync to current plate-solved position |
| **2** | South | Move mount south (decreasing Dec) |
| **3** | Sync | Sync mount to current plate-solved coordinates |
| **4** | West | Move mount west (increasing RA) |
| **5** | GoTo Target | Slew mount to currently displayed object |
| **6** | East | Move mount east (decreasing RA) |
| **8** | North | Move mount north (increasing Dec) |

**Step Size Adjustment for manual moves**
Not yet implemented. 

### Typical Workflow

1. **Initialize Mount**
   - Ensure INDI server is running and mount driver is connected
   - Point PiFinder at a known star or object
   - Wait for plate solve to complete
   - Press **1** to initialize mount and sync to solved position

Tipp: Press **1** once, to have the mount tracking.

2. **Navigate to Target**
   - Browse or search for your desired object in PiFinder
   - View object details to see coordinates and information
   - Press **5** to command mount to slew to target

3. **Target Refinement** (Automatic)
   - After the mount reports it has reached the target, PiFinder automatically:
     - Waits for a new plate solve
     - Compares solved position to target position
     - Syncs mount and performs additional slew if needed (>0.01° error in one of the axes)
     - Repeats until target is centered within 0.01° (36 arcseconds)

4. **Coarse Adjustments**
   - Use directional keys (**2, 4, 6, 8**) for manual adjustments
   - Those use the largest step size available for the mount, so this may be of limited use at the moment.
   
5. **Emergency Stop**
   - Press **0** at any time to immediately stop mount movement

### Mount Control Phases

The mount control system operates in distinct phases visible in the logs:

- **MOUNT_INIT_TELESCOPE**: Connecting and initializing mount hardware
- **MOUNT_STOPPED**: Mount is stopped, waiting for commands
- **MOUNT_TRACKING**: Mount is tracking the sky (after manual movements)
- **MOUNT_TARGET_ACQUISITION_MOVE**: Mount is slewing to target coordinates
- **MOUNT_TARGET_ACQUISITION_REFINE**: Refining target position using plate-solved coordinates
- **MOUNT_DRIFT_COMPENSATION**: (Future) Active drift compensation during tracking

### Mount Not Responding

1. Check INDI server is running: `systemctl status indiwebmanager.service`
2. Verify mount driver is started in INDI Web Manager
3. Check mount driver shows "Connected" status
4. Try pressing **1** to reinitialize mount connection
5. Review logs: `journalctl -u pifinder -f | grep MountControl`

### Plate Solving Required

Many mount control features require an active plate solve:
- **Sync (Key 3)**: Requires solved position to sync mount
- **Init (Key 1)**: Works better with solved position for initial sync
- **Target Refinement**: Requires solve after slew to refine position

If plate solving fails:
- Ensure camera is working and capturing images
- Check focus - stars must be sharp for solving
- Verify sufficient stars are visible in frame
- Check exposure time is appropriate for sky conditions

### Position Accuracy

The target refinement process achieves 0.01° (36 arcsecond) accuracy by:
1. Initial GoTo slew to target coordinates
2. Plate solve to determine actual pointing
3. Sync mount to solved position
4. Additional slew to target if error > 0.01°
5. Repeat until accuracy achieved

For better accuracy:
- Ensure good polar alignment
- Use proper guide rates for manual adjustments
- Sync frequently using plate-solved positions
- Allow time for mount to settle after movements

### Time Synchronization

Accurate mount pointing requires correct time and location:
- GPS is used to set time and location automatically
- Chrony syncs system time from GPS (installed by setup script)
- Verify GPS is working: Check PiFinder GPS status
- Manually set timezone: `sudo raspi-config` > Localisation Options

## Known Limitations

- **Drift Compensation**: Not yet fully implemented
- **Spiral Search**: Planned feature, not yet available
- **Mount Parking**: Not implemented
- **Multiple Mounts**: Only one mount can be controlled at a time
- **Alt-Az Mounts**: Should work, not tested, check if your mount driver supports it.

## Support and Development

### Logging

Mount control operations are logged with the "MountControl" logger:

```bash
# View mount control logs in real-time
journalctl -u pifinder -f | grep MountControl

# View PyIndi client logs
journalctl -u pifinder -f | grep "MountControl.Indi"
```

### Reporting Issues

When reporting mount control issues, please include:
- Mount make and model
- INDI driver name and version
- PiFinder logs showing the issue
- Whether mount responds in INDI Web Manager
- Description of behavior vs. expected behavior

### Contributing

Mount control is designed to be extensible:
- New mount backends can be added by subclassing `MountControlBase`
- Current implementation supports any INDI-compatible mount
- Future backends could support other protocols (ASCOM, NexStar, etc.)

## References

- **INDI Library**: https://github.com/indilib/indi
- **INDI Web Manager**: https://github.com/rkaczorek/indiwebmanager
- **PyIndi**: https://github.com/indilib/pyindi-client
- **PiFinder Documentation**: https://github.com/brickbots/PiFinder
