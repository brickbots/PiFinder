% include("header.tpl", title="Location Management")
<style>
  .input-field input.invalid {
    border-bottom: 1px solid #F44336 !important;
    box-shadow: 0 1px 0 0 #F44336 !important;
  }
  .input-field input.invalid + label {
    color: #F44336 !important;
  }
  .helper-text {
    color: #F44336;
    font-size: 12px;
    margin-top: 5px;
    min-height: 12px;
  }
  .helper-text.red-text {
    color: #F44336;
  }
</style>
<div class="row valign-wrapper" style="margin: 0px;">
  <div class="col s12">
    <h5 class="grey-text">Location Management</h5>
  </div>
</div>

<div class="card grey darken-2">
  <div class="card-content">
    <div class="row">
      <div class="col s12">
        <a href="/locations?add_new=1" class="waves-effect waves-light btn">
          <i class="material-icons left">add</i>Add New Location
        </a>
      </div>
    </div>

    % if show_new_form:
    <div class="row">
      <form action="/locations/add" method="post" class="col s12" id="location_form">
        <div class="row">
          <div class="input-field col s12">
            <input id="name" type="text" name="name" required/>
            <label for="name">Location Name</label>
          </div>
        </div>
        <div class="row">
          <div class="input-field col s12">
            <label>
              <input type="checkbox" id="formatSwitch" onclick="toggleFormat()"/>
              <span>Use DMS Format</span>
            </label>
          </div>
        </div>
        <div class="row" id="decimalFormat">
          <div class="input-field col s4">
            <input id="latitude" type="number" step="any" name="latitude" required/>
            <label for="latitude">Latitude (Decimal)</label>
            <span class="helper-text" data-error="Invalid latitude"></span>
          </div>
          <div class="input-field col s4">
            <input id="longitude" type="number" step="any" name="longitude" required/>
            <label for="longitude">Longitude (Decimal)</label>
            <span class="helper-text" data-error="Invalid longitude"></span>
          </div>
          <div class="input-field col s4">
            <input id="altitude" type="number" step="any" name="altitude" required/>
            <label for="altitude">Altitude (meters)</label>
            <span class="helper-text" data-error="Invalid altitude"></span>
          </div>
        </div>
        <div class="row" id="dmsFormat" style="display:none;">
          <div class="input-field col s4">
            <input id="latitudeD" type="number" name="latitudeD"/>
            <label for="latitudeD">Latitude Degrees</label>
          </div>
          <div class="input-field col s4">
            <input id="latitudeM" type="number" name="latitudeM"/>
            <label for="latitudeM">Latitude Minutes</label>
          </div>
          <div class="input-field col s4">
            <input id="latitudeS" type="number" name="latitudeS"/>
            <label for="latitudeS">Latitude Seconds</label>
          </div>
          <div class="input-field col s4">
            <input id="longitudeD" type="number" name="longitudeD"/>
            <label for="longitudeD">Longitude Degrees</label>
          </div>
          <div class="input-field col s4">
            <input id="longitudeM" type="number" name="longitudeM"/>
            <label for="longitudeM">Longitude Minutes</label>
          </div>
          <div class="input-field col s4">
            <input id="longitudeS" type="number" name="longitudeS"/>
            <label for="longitudeS">Longitude Seconds</label>
          </div>
        </div>
        <div class="row">
          <div class="input-field col s6">
            <input id="error_in_m" type="number" step="any" name="error_in_m" value="0"/>
            <label for="error_in_m">Error (meters)</label>
          </div>
          <div class="input-field col s6">
            <input id="source" type="text" name="source" value="Manual Entry"/>
            <label for="source">Source</label>
          </div>
        </div>
        <div class="row">
          <div class="col s12">
            <button type="submit" id="saveButton" class="waves-effect waves-light btn">Save Location</button>
            <a href="/locations" class="waves-effect waves-light btn grey">Cancel</a>
          </div>
        </div>
      </form>
    </div>
    % end

    <div class="row">
      <div class="col s12">
        <table class="striped">
          <thead>
            <tr>
              <th>Name</th>
              <th>Latitude</th>
              <th>Longitude</th>
              <th>Altitude</th>
              <th>Error</th>
              <th>Source</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            % for i, location in enumerate(locations):
            <tr>
              <td>
                % if location.is_default:
                <i class="material-icons tiny">star</i>
                % end
                {{ location.name }}
              </td>
              <td>{{ f"{location.latitude:.6f}" }}</td>
              <td>{{ f"{location.longitude:.6f}" }}</td>
              <td>{{ f"{location.height:.1f}m" }}</td>
              <td>{{ f"{location.error_in_m:.1f}m" }}</td>
              <td>{{ location.source }}</td>
              <td>
                <a href="/locations/load/{{ i }}" class="waves-effect waves-light btn-small" title="Load Location">
                  <i class="material-icons">location_on</i>
                </a>
                <a href="/locations/set_default/{{ i }}" class="waves-effect waves-light btn-small" title="Set as Default">
                  <i class="material-icons">star</i>
                </a>
                <a href="#rename-modal-{{ i }}" class="waves-effect waves-light btn-small modal-trigger" title="Edit">
                  <i class="material-icons">edit</i>
                </a>
                <a href="/locations/delete/{{ i }}" class="waves-effect waves-light btn-small red" title="Delete">
                  <i class="material-icons">delete</i>
                </a>
              </td>
            </tr>
            % end
          </tbody>
        </table>
      </div>
    </div>
  </div>
</div>

% for i, location in enumerate(locations):
<div id="rename-modal-{{ i }}" class="modal">
  <div class="modal-content">
    <h4>Edit Location</h4>
    <form action="/locations/rename/{{ i }}" method="post" id="edit_form_{{ i }}">
      <div class="row">
        <div class="input-field col s12">
          <input id="rename-name-{{ i }}" type="text" name="name" value="{{ location.name }}" required/>
          <label for="rename-name-{{ i }}">Location Name</label>
        </div>
      </div>
      <div class="row">
        <div class="input-field col s12">
          <label>
            <input type="checkbox" id="formatSwitch-{{ i }}" onclick="toggleFormat('{{ i }}')"/>
            <span>Use DMS Format</span>
          </label>
        </div>
      </div>
      <div class="row" id="decimalFormat-{{ i }}">
        <div class="input-field col s4">
          <input id="rename-latitude-{{ i }}" type="number" step="any" name="latitude" value="{{ location.latitude }}" required/>
          <label for="rename-latitude-{{ i }}">Latitude (Decimal)</label>
          <span class="helper-text" data-error="Invalid latitude"></span>
        </div>
        <div class="input-field col s4">
          <input id="rename-longitude-{{ i }}" type="number" step="any" name="longitude" value="{{ location.longitude }}" required/>
          <label for="rename-longitude-{{ i }}">Longitude (Decimal)</label>
          <span class="helper-text" data-error="Invalid longitude"></span>
        </div>
        <div class="input-field col s4">
          <input id="rename-altitude-{{ i }}" type="number" step="any" name="altitude" value="{{ location.height }}" required/>
          <label for="rename-altitude-{{ i }}">Altitude (meters)</label>
          <span class="helper-text" data-error="Invalid altitude"></span>
        </div>
      </div>
      <div class="row" id="dmsFormat-{{ i }}" style="display:none;">
        <div class="input-field col s4">
          <input id="rename-latitudeD-{{ i }}" type="number" name="latitudeD"/>
          <label for="rename-latitudeD-{{ i }}">Latitude Degrees</label>
        </div>
        <div class="input-field col s4">
          <input id="rename-latitudeM-{{ i }}" type="number" name="latitudeM"/>
          <label for="rename-latitudeM-{{ i }}">Latitude Minutes</label>
        </div>
        <div class="input-field col s4">
          <input id="rename-latitudeS-{{ i }}" type="number" name="latitudeS"/>
          <label for="rename-latitudeS-{{ i }}">Latitude Seconds</label>
        </div>
        <div class="input-field col s4">
          <input id="rename-longitudeD-{{ i }}" type="number" name="longitudeD"/>
          <label for="rename-longitudeD-{{ i }}">Longitude Degrees</label>
        </div>
        <div class="input-field col s4">
          <input id="rename-longitudeM-{{ i }}" type="number" name="longitudeM"/>
          <label for="rename-longitudeM-{{ i }}">Longitude Minutes</label>
        </div>
        <div class="input-field col s4">
          <input id="rename-longitudeS-{{ i }}" type="number" name="longitudeS"/>
          <label for="rename-longitudeS-{{ i }}">Longitude Seconds</label>
        </div>
      </div>
      <div class="row">
        <div class="input-field col s6">
          <input id="rename-error-{{ i }}" type="number" step="any" name="error_in_m" value="{{ location.error_in_m }}"/>
          <label for="rename-error-{{ i }}">Error (meters)</label>
        </div>
        <div class="input-field col s6">
          <input id="rename-source-{{ i }}" type="text" name="source" value="{{ location.source }}"/>
          <label for="rename-source-{{ i }}">Source</label>
        </div>
      </div>
      <div class="modal-footer">
        <button type="submit" id="saveButton-{{ i }}" class="waves-effect waves-light btn">Save Changes</button>
        <a href="#!" class="modal-close waves-effect waves-light btn grey">Cancel</a>
      </div>
    </form>
  </div>
</div>
% end

<script>
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
        degrees += (decimal >= 0 ? 1 : -1);
    }

    return [degrees, minutes, seconds];
}

// Conversion from DMS to Decimal
function DMSToDecimal(degrees, minutes, seconds) {
    var sign = degrees < 0 ? -1 : 1;
    return sign * (Math.abs(degrees) + (minutes / 60) + (seconds / 3600));
}

function validateDMSFields(id = '') {
    var latD = document.getElementById("latitudeD" + (id ? '-' + id : ''));
    var latM = document.getElementById("latitudeM" + (id ? '-' + id : ''));
    var latS = document.getElementById("latitudeS" + (id ? '-' + id : ''));
    var longD = document.getElementById("longitudeD" + (id ? '-' + id : ''));
    var longM = document.getElementById("longitudeM" + (id ? '-' + id : ''));
    var longS = document.getElementById("longitudeS" + (id ? '-' + id : ''));
    
    if (!latD || !latM || !latS || !longD || !longM || !longS) return false;
    
    var lat = DMSToDecimal(parseFloat(latD.value), parseFloat(latM.value), parseFloat(latS.value));
    var lon = DMSToDecimal(parseFloat(longD.value), parseFloat(longM.value), parseFloat(longS.value));
    
    return validateField(lat, 'latitude') && validateField(lon, 'longitude');
}

function updateDMSFields(decimalLatitude, decimalLongitude, id = '') {
    if (decimalLatitude) {
        var dmsLat = decimalToDMS(parseFloat(decimalLatitude));
        var latD = document.getElementById("latitudeD" + (id ? '-' + id : ''));
        var latM = document.getElementById("latitudeM" + (id ? '-' + id : ''));
        var latS = document.getElementById("latitudeS" + (id ? '-' + id : ''));

        latD.value = dmsLat[0];
        latM.value = dmsLat[1];
        latS.value = dmsLat[2];
    }

    if (decimalLongitude) {
        var dmsLong = decimalToDMS(parseFloat(decimalLongitude));
        var longD = document.getElementById("longitudeD" + (id ? '-' + id : ''));
        var longM = document.getElementById("longitudeM" + (id ? '-' + id : ''));
        var longS = document.getElementById("longitudeS" + (id ? '-' + id : ''));

        longD.value = dmsLong[0];
        longM.value = dmsLong[1];
        longS.value = dmsLong[2];
    }
    
    checkFields(id);
}

function toggleFormat(id = '') {
    var checkBox = document.getElementById("formatSwitch" + (id ? '-' + id : ''));
    var decimalFormat = document.getElementById("decimalFormat" + (id ? '-' + id : ''));
    var dmsFormat = document.getElementById("dmsFormat" + (id ? '-' + id : ''));
    if (checkBox.checked == true){
        decimalFormat.style.display = "none";
        dmsFormat.style.display = "block";
        focusFirstDMSField(id);
        // Add event listeners for DMS fields
        setupDMSValidation(id);
    } else {
        decimalFormat.style.display = "block";
        dmsFormat.style.display = "none";
    }
    checkFields(id);
}

function setupDMSValidation(id = '') {
    var dmsFields = [
        "latitudeD", "latitudeM", "latitudeS",
        "longitudeD", "longitudeM", "longitudeS"
    ];
    
    dmsFields.forEach(function(field) {
        var element = document.getElementById(field + (id ? '-' + id : ''));
        if (element) {
            element.addEventListener('input', function() {
                checkFields(id);
            });
        }
    });
}

function focusFirstDMSField(id = '') {
    var latS = document.getElementById("latitudeS" + (id ? '-' + id : ''));
    var latM = document.getElementById("latitudeM" + (id ? '-' + id : ''));
    var latD = document.getElementById("latitudeD" + (id ? '-' + id : ''));
    var longS = document.getElementById("longitudeS" + (id ? '-' + id : ''));
    var longM = document.getElementById("longitudeM" + (id ? '-' + id : ''));
    var longD = document.getElementById("longitudeD" + (id ? '-' + id : ''));

    if (latS.offsetParent !== null) {
        latS.focus();
        latM.focus();
        latD.focus();
        longS.focus();
        longM.focus();
        longD.focus();
    } else {
        setTimeout(function() { focusFirstDMSField(id); }, 50);
    }
}

function validateField(value, fieldName) {
    if (!value || isNaN(value)) {
        return false;
    }
    
    switch(fieldName) {
        case 'latitude':
            return value >= -90 && value <= 90;
        case 'longitude':
            return value >= -180 && value <= 180;
        case 'altitude':
            return value >= -1000 && value <= 10000; // Reasonable range for altitude in meters
        default:
            return true;
    }
}

function updateFieldValidation(field, fieldName, id = '') {
    var helperText = field.parentElement.querySelector('.helper-text');
    var isValid = validateField(field.value, fieldName);
    
    if (!isValid) {
        field.classList.add('invalid');
        helperText.classList.add('red-text');
        helperText.textContent = helperText.getAttribute('data-error');
    } else {
        field.classList.remove('invalid');
        helperText.classList.remove('red-text');
        helperText.textContent = '';
    }
    
    return isValid;
}

function checkFields(id = '') {
    var checkBox = document.getElementById("formatSwitch" + (id ? '-' + id : ''));
    var saveButton = document.getElementById('saveButton' + (id ? '-' + id : ''));
    
    var isValid = false;
    if (checkBox && checkBox.checked) {
        isValid = validateDMSFields(id);
    } else {
        var latitude = document.getElementById('latitude' + (id ? '-' + id : ''));
        var longitude = document.getElementById('longitude' + (id ? '-' + id : ''));
        var altitude = document.getElementById('altitude' + (id ? '-' + id : ''));
        
        var latValid = updateFieldValidation(latitude, 'latitude', id);
        var lonValid = updateFieldValidation(longitude, 'longitude', id);
        var altValid = updateFieldValidation(altitude, 'altitude', id);
        
        isValid = latValid && lonValid && altValid;
    }
    
    if (saveButton) {
        saveButton.disabled = !isValid;
    }
    
    return isValid;
}

document.addEventListener('DOMContentLoaded', function() {
    var elems = document.querySelectorAll('.modal');
    var instances = M.Modal.init(elems);

    // Initialize all forms
    var forms = document.querySelectorAll('form[id^="edit_form_"]');
    forms.forEach(function(form) {
        var id = form.id.split('_')[2];
        var lat = document.getElementById('rename-latitude-' + id);
        var lon = document.getElementById('rename-longitude-' + id);
        var alt = document.getElementById('rename-altitude-' + id);
        
        // Set up event listeners
        lat.addEventListener('input', function() {
            updateDMSFields(this.value, null, id);
            updateFieldValidation(this, 'latitude', id);
            checkFields(id);
        });
        
        lon.addEventListener('input', function() {
            updateDMSFields(null, this.value, id);
            updateFieldValidation(this, 'longitude', id);
            checkFields(id);
        });
        
        alt.addEventListener('input', function() {
            updateFieldValidation(this, 'altitude', id);
            checkFields(id);
        });
        
        // Set up form submission
        form.addEventListener('submit', function(e) {
            if (!checkFields(id)) {
                e.preventDefault();
                M.toast({html: 'Please fix the validation errors before saving', classes: 'red'});
            }
        });
        
        // Initial validation
        if (lat) updateFieldValidation(lat, 'latitude', id);
        if (lon) updateFieldValidation(lon, 'longitude', id);
        if (alt) updateFieldValidation(alt, 'altitude', id);
        checkFields(id);
    });

    // Set up main form
    var mainForm = document.getElementById('location_form');
    if (mainForm) {
        var lat = document.getElementById('latitude');
        var lon = document.getElementById('longitude');
        var alt = document.getElementById('altitude');
        
        if (lat && lon && alt) {
            lat.addEventListener('input', function() {
                updateDMSFields(this.value, null);
                updateFieldValidation(this, 'latitude');
                checkFields();
            });
            
            lon.addEventListener('input', function() {
                updateDMSFields(null, this.value);
                updateFieldValidation(this, 'longitude');
                checkFields();
            });
            
            alt.addEventListener('input', function() {
                updateFieldValidation(this, 'altitude');
                checkFields();
            });
            
            // Set up form submission
            mainForm.addEventListener('submit', function(e) {
                if (!checkFields()) {
                    e.preventDefault();
                    M.toast({html: 'Please fix the validation errors before saving', classes: 'red'});
                }
            });
            
            // Initial validation
            updateFieldValidation(lat, 'latitude');
            updateFieldValidation(lon, 'longitude');
            updateFieldValidation(alt, 'altitude');
            checkFields();
        }
    }
});
</script>

% include("footer.tpl") 