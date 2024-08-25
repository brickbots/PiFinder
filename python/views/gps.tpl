% include("header.tpl", title="GPS Settings")
<div class="row valign-wrapper" style="margin: 0px;">
  <div class="col s12">
        <h5 class="grey-text">GPS Settings</h5>
  </div>
</div>
<div class="card grey darken-2">
  <div class="card-content">
    <form action="/gps/update" method="post" id="gps_form" class="col s12">
        <div class="row">
            <div class="input-field col s12">
                <label>
                    <input type="checkbox" id="formatSwitch" onclick="toggleFormat()"/>
                    <span>Use DMS Format</span>
                </label>
            </div>
        </div>
        <div class="row" id="decimalFormat">
            <div class="input-field col s6">
                <input id="latitudeDecimal" type="text" name="latitudeDecimal" value="{{ lat if lat is not None else '' }}"/>
                <label for="latitudeDecimal">Latitude (Decimal)</label>
            </div>
            <div class="input-field col s6">
                <input id="longitudeDecimal" type="text" name="longitudeDecimal" value="{{ lon if lon is not None else '' }}"/>
                <label for="longitudeDecimal">Longitude (Decimal)</label>
            </div>
        </div>
        <div class="row" id="dmsFormat" style="display:none;">
            <div class="input-field col s4">
                <input id="latitudeD" type="text" name="latitudeD"/>
                <label for="latitudeD">Latitude Degrees</label>
            </div>
            <div class="input-field col s4">
                <input id="latitudeM" type="text" name="latitudeM"/>
                <label for="latitudeM">Latitude Minutes</label>
            </div>
            <div class="input-field col s4">
                <input id="latitudeS" type="text" name="latitudeS"/>
                <label for="latitudeS">Latitude Seconds</label>
            </div>
            <div class="input-field col s4">
                <input id="longitudeD" type="text" name="longitudeD"/>
                <label for="longitudeD">Longitude Degrees</label>
            </div>
            <div class="input-field col s4">
                <input id="longitudeM" type="text" name="longitudeM"/>
                <label for="longitudeM">Longitude Minutes</label>
            </div>
            <div class="input-field col s4">
                <input id="longitudeS" type="text" name="longitudeS"/>
                <label for="longitudeS">Longitude Seconds</label>
            </div>
        </div>
        <div class="row">
            <div class="input-field col s8">
                <input id="altitude" type="text" name="altitude" value="{{ altitude if altitude is not None else '' }}"/>
                <label for="altitude">Altitude in meter</label>
            </div>
            </div>
        <div class="row">
            <div class="input-field col s4">
                <input id="date" type="date" name="date"/>
                <label for="date">Date</label>
            </div>
            <div class="input-field col s4">
                <input id="time" type="text" name="time"/>
                <label for="time">UTC Time (h:m:s)</label>
            </div>
            <div class="input-field col s8">
                 <button type="button" class="waves-effect waves-light btn" onclick="setBrowserDateTime()">Set to Browser Date/Time</button>
            </div>
        </div>
        <div class="row">
            <div class="col s12">
                <button type="submit" id="saveButton" class="waves-effect waves-light btn">Save</button>
            </div>
        </div>
    </form>
  </div>
</div>
<script>
function toggleFormat() {
    var checkBox = document.getElementById("formatSwitch");
    var decimalFormat = document.getElementById("decimalFormat");
    var dmsFormat = document.getElementById("dmsFormat");
    if (checkBox.checked == true){
        decimalFormat.style.display = "none";
        dmsFormat.style.display = "block";
        focusFirstDMSField();
    } else {
        decimalFormat.style.display = "block";
        dmsFormat.style.display = "none";
    }
}

function focusFirstDMSField() {
    var latS = document.getElementById("latitudeS");
    var latM = document.getElementById("latitudeM");
    var latD = document.getElementById("latitudeD");
    var longS = document.getElementById("longitudeS");
    var longM = document.getElementById("longitudeM");
    var longD = document.getElementById("longitudeD");

    if (latS.offsetParent !== null) {
        // Sequentially set focus
        latS.focus();
        latM.focus();
        latD.focus();
        longS.focus();
        longM.focus();
        longD.focus();
    } else {
        // Retry if not visible
        setTimeout(focusFirstDMSField, 50);
    }
}


function setBrowserTime() {
    var now = new Date();
    var dateString = now.toISOString().split('T')[0]; // Extract date in YYYY-MM-DD format
    var timeString = now.getUTCHours() + ":" + now.getUTCMinutes() + ":" + now.getUTCSeconds();

    document.getElementById("date").value = dateString;
    document.getElementById("time").value = timeString;

    // Set focus to the 'date' field if needed
    document.getElementById("date").focus();
}

document.addEventListener('DOMContentLoaded', function () {
    // Existing initialization code
    var elems = document.querySelectorAll('select');
    var instances = M.FormSelect.init(elems);

    var modalElems = document.querySelectorAll('.modal');
    var modalInstances = M.Modal.init(modalElems);

       // Function to check if all fields are filled with numbers
    function checkFields() {
        var latitude = document.getElementById('latitudeDecimal').value;
        var longitude = document.getElementById('longitudeDecimal').value;
        var altitude = document.getElementById('altitude').value;
        var saveButton = document.getElementById('saveButton');

        // Check if all fields are not empty and contain valid numbers
        if (latitude && !isNaN(latitude) &&
            longitude && !isNaN(longitude) &&
            altitude && !isNaN(altitude)) {
            saveButton.disabled = false;
        } else {
            saveButton.disabled = true;
        }
    }

    // Event listeners for input fields
    document.getElementById('latitudeDecimal').addEventListener('input', checkFields);
    document.getElementById('longitudeDecimal').addEventListener('input', checkFields);
    document.getElementById('altitude').addEventListener('input', checkFields);

    // Initial check on page load
    checkFields();

    setBrowserDateTime();

    // Convert decimal to DMS on page load if fields are pre-filled
    convertDecimalToDMS();
});

// Conversion from Decimal to DMS
function decimalToDMS(decimal) {
    var degrees = Math.floor(decimal);
    var minutes = Math.floor((Math.abs(decimal) * 3600) / 60) % 60;
    var seconds = Math.abs(decimal * 3600) % 60;

    // Round seconds to 2 decimal places
    seconds = Math.round(seconds * 100) / 100;

    // Handle the case where seconds round up to 60
    if (seconds === 60) {
        seconds = 0;
        minutes += 1;
    }

    // Handle the case where minutes round up to 60
    if (minutes === 60) {
        minutes = 0;
        degrees += (decimal >= 0 ? 1 : -1); // Increment or decrement degrees based on sign
    }

    return [degrees, minutes, seconds];
}


// Conversion from DMS to Decimal
function DMSToDecimal(degrees, minutes, seconds) {
    var sign = degrees < 0 ? -1 : 1;
    return sign * (Math.abs(degrees) + (minutes / 60) + (seconds / 3600));
}

function updateDMSFields(decimalLatitude, decimalLongitude) {
    if (decimalLatitude) {
        var dmsLat = decimalToDMS(parseFloat(decimalLatitude));
        var latD = document.getElementById("latitudeD");
        var latM = document.getElementById("latitudeM");
        var latS = document.getElementById("latitudeS");

        latD.value = dmsLat[0];
        latM.value = dmsLat[1];
        latS.value = dmsLat[2];
    }

    if (decimalLongitude) {
        var dmsLong = decimalToDMS(parseFloat(decimalLongitude));
        var longD = document.getElementById("longitudeD");
        var longM = document.getElementById("longitudeM");
        var longS = document.getElementById("longitudeS");

        longD.value = dmsLong[0];
        longM.value = dmsLong[1];
        longS.value = dmsLong[2];
    }
}

// Use the same function for initial conversion and event listeners
function convertDecimalToDMS() {
    var latDecimal = document.getElementById("latitudeDecimal").value;
    var longDecimal = document.getElementById("longitudeDecimal").value;
    updateDMSFields(latDecimal, longDecimal);
}

document.getElementById("latitudeDecimal").addEventListener("input", function () {
    updateDMSFields(this.value, null);
});

document.getElementById("longitudeDecimal").addEventListener("input", function () {
    updateDMSFields(null, this.value);
});

document.getElementById("altitude").addEventListener("input", function () {
    updateDMSFields(null, this.value);
});

// Update Decimal Latitude on DMS Latitude Change
function updateDecimalLatitude() {
    var degrees = parseFloat(document.getElementById("latitudeD").value) || 0;
    var minutes = parseFloat(document.getElementById("latitudeM").value) || 0;
    var seconds = parseFloat(document.getElementById("latitudeS").value) || 0;
    var decimal = DMSToDecimal(degrees, minutes, seconds);
    document.getElementById("latitudeDecimal").value = decimal;
}

// Update Decimal Longitude on DMS Longitude Change
function updateDecimalLongitude() {
    var degrees = parseFloat(document.getElementById("longitudeD").value) || 0;
    var minutes = parseFloat(document.getElementById("longitudeM").value) || 0;
    var seconds = parseFloat(document.getElementById("longitudeS").value) || 0;
    var decimal = DMSToDecimal(degrees, minutes, seconds);
    document.getElementById("longitudeDecimal").value = decimal;
}

// Latitude DMS Change Listeners
document.getElementById("latitudeD").addEventListener("input", updateDecimalLatitude);
document.getElementById("latitudeM").addEventListener("input", updateDecimalLatitude);
document.getElementById("latitudeS").addEventListener("input", updateDecimalLatitude);

// Longitude DMS Change Listeners
document.getElementById("longitudeD").addEventListener("input", updateDecimalLongitude);
document.getElementById("longitudeM").addEventListener("input", updateDecimalLongitude);
document.getElementById("longitudeS").addEventListener("input", updateDecimalLongitude);

</script>

% include("footer.tpl")
