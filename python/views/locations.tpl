% include("header.tpl", title="Location Management")
<style>
  .input-field {
    position: relative;
    margin-bottom: 20px;
  }
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
    position: absolute;
    bottom: -18px;
    left: 0;
    width: 100%;
    min-height: 12px;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
</style>
<div class="row valign-wrapper" style="margin: 0px;">
  <div class="col s12">
    <h5 class="grey-text">Location Management</h5>
  </div>
</div>

<div class="card grey darken-2">
  <div class="card-content">
    % if defined('error_message'):
    <div class="row">
        <div class="col s12">
            <span class="red-text">{{ error_message }}</span>
        </div>
    </div>
    % end

    <div class="row">
      <div class="col s12">
        <a href="/locations?add_new=1" class="waves-effect waves-light btn">
          <i class="material-icons left">add</i>Add New Location
        </a>
      </div>
    </div>

    % if show_new_form:
    % include("location_form.tpl", action="/locations/add", form_id="location_form", name="", latitude="", longitude="", altitude="", error_in_m="0", source="Manual Entry", submit_text="Save Location", cancel_url="/locations", cancel_class="")
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
                <a href="#delete-modal-{{ i }}" class="waves-effect waves-light btn-small red modal-trigger" title="Delete">
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
    % include("location_form.tpl", action="/locations/rename/" + str(i), form_id="edit_form_" + str(i), name=location.name, latitude=str(location.latitude), longitude=str(location.longitude), altitude=str(location.height), error_in_m=str(location.error_in_m), source=location.source, submit_text="Save Changes", cancel_url="#!", cancel_class="modal-close")
  </div>
</div>
<div id="delete-modal-{{ i }}" class="modal">
  <div class="modal-content">
    <h4>Confirm Delete</h4>
    <p>Are you sure you want to delete the location "<strong>{{ location.name }}</strong>"? This action cannot be undone.</p>
  </div>
  <div class="modal-footer">
    <a href="#!" class="modal-close waves-effect waves-light btn grey">Cancel</a>
    <a href="/locations/delete/{{ i }}" class="modal-close waves-effect waves-light btn red">Delete</a>
  </div>
</div>
% end

<script>
// Conversion from Decimal to DMS
function decimalToDMS(decimal) {
    var degrees = Math.floor(decimal);
    var minutes = Math.floor((Math.abs(decimal) * 3600) / 60) % 60;
    var seconds = Math.abs(decimal * 3600) % 60;
    seconds = Math.round(seconds * 100) / 100;
    if (seconds === 60) {
        seconds = 0;
        minutes += 1;
    }
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
    var latD = document.getElementById("latitudeD-" + id);
    var latM = document.getElementById("latitudeM-" + id);
    var latS = document.getElementById("latitudeS-" + id);
    var longD = document.getElementById("longitudeD-" + id);
    var longM = document.getElementById("longitudeM-" + id);
    var longS = document.getElementById("longitudeS-" + id);
    
    if (!latD || !latM || !latS || !longD || !longM || !longS) return false;
    
    var lat = DMSToDecimal(parseFloat(latD.value), parseFloat(latM.value), parseFloat(latS.value));
    var lon = DMSToDecimal(parseFloat(longD.value), parseFloat(longM.value), parseFloat(longS.value));
    
    return validateField(lat, 'latitude') && validateField(lon, 'longitude');
}

function updateDMSFields(decimalLatitude, decimalLongitude, id = '') {
    if (decimalLatitude) {
        var dmsLat = decimalToDMS(parseFloat(decimalLatitude));
        document.getElementById("latitudeD-" + id).value = dmsLat[0];
        document.getElementById("latitudeM-" + id).value = dmsLat[1];
        document.getElementById("latitudeS-" + id).value = dmsLat[2];
    }
    if (decimalLongitude) {
        var dmsLong = decimalToDMS(parseFloat(decimalLongitude));
        document.getElementById("longitudeD-" + id).value = dmsLong[0];
        document.getElementById("longitudeM-" + id).value = dmsLong[1];
        document.getElementById("longitudeS-" + id).value = dmsLong[2];
    }
    checkFields(id);
}

function toggleFormat(id = '') {
    var checkBox = document.getElementById("formatSwitch-" + id);
    var decimalFormat = document.getElementById("decimalFormat-" + id);
    var dmsFormat = document.getElementById("dmsFormat-" + id);
    if (checkBox.checked) {
        decimalFormat.style.display = "none";
        dmsFormat.style.display = "block";
        focusFirstDMSField(id);
        setupDMSValidation(id);
    } else {
        decimalFormat.style.display = "block";
        dmsFormat.style.display = "none";
    }
    checkFields(id);
}

function setupDMSValidation(id = '') {
    var dmsFields = ["latitudeD", "latitudeM", "latitudeS", "longitudeD", "longitudeM", "longitudeS"];
    dmsFields.forEach(function(field) {
        var element = document.getElementById(field + "-" + id);
        if (element) {
            element.addEventListener('input', function() {
                checkFields(id);
            });
        }
    });
}

function focusFirstDMSField(id = '') {
    var latS = document.getElementById("latitudeS-" + id);
    if (latS.offsetParent !== null) {
        ["latitudeS", "latitudeM", "latitudeD", "longitudeS", "longitudeM", "longitudeD"].forEach(field => {
            document.getElementById(field + "-" + id).focus();
        });
    } else {
        setTimeout(function() { focusFirstDMSField(id); }, 50);
    }
}

function validateField(value, fieldName) {
    if (value === '' || value === null) return false;
    const numValue = parseFloat(value);
    if (isNaN(numValue)) return false;
    
    switch(fieldName) {
        case 'latitude':
            return numValue >= -90 && numValue <= 90;
        case 'longitude':
            return numValue >= -180 && numValue <= 180;
        case 'altitude':
            return numValue >= -1000 && numValue <= 10000;
        case 'error_in_m':
            return numValue >= 0 && numValue <= 10000;
        default:
            return true;
    }
}

function updateFieldValidation(field, fieldName, id = '', forceShowError = false) {
    const helperText = field.parentElement.querySelector('.helper-text');
    const value = field.value.trim();
    const isValid = validateField(value, fieldName);
    const showError = forceShowError || field.dataset.hasInteracted === 'true';
    
    field.classList.remove('invalid');
    helperText.classList.remove('red-text');
    helperText.textContent = '';
    
    if (showError && !isValid) {
        field.classList.add('invalid');
        helperText.classList.add('red-text');
        if (value === '') {
            helperText.textContent = 'This field is required';
        } else if (isNaN(parseFloat(value))) {
            helperText.textContent = 'Must be a valid number';
        } else {
            switch(fieldName) {
                case 'latitude':
                    helperText.textContent = 'Must be between -90 and 90';
                    break;
                case 'longitude':
                    helperText.textContent = 'Must be between -180 and 180';
                    break;
                case 'altitude':
                    helperText.textContent = 'Must be between -1000 and 10000 meters';
                    break;
                case 'error_in_m':
                    helperText.textContent = 'Must be between 0 and 10000 meters';
                    break;
            }
        }
    }
    return isValid;
}

function checkFields(id = '') {
    const checkBox = document.getElementById("formatSwitch-" + id);
    const saveButton = document.getElementById("saveButton-" + id);
    const nameField = document.getElementById("name-" + id);
    
    let isValid = nameField && nameField.value.trim() !== '';
    
    if (checkBox && checkBox.checked) {
        isValid = isValid && validateDMSFields(id);
    } else {
        const fields = {
            latitude: document.getElementById("latitude-" + id),
            longitude: document.getElementById("longitude-" + id),
            altitude: document.getElementById("altitude-" + id),
            error_in_m: document.getElementById("error_in_m-" + id)
        };
        
        isValid = isValid && Object.entries(fields).every(([fieldName, field]) => 
            field && validateField(field.value, fieldName)
        );
    }
    
    if (saveButton) {
        saveButton.disabled = !isValid;
    }
    return isValid;
}

document.addEventListener('DOMContentLoaded', function() {
    var elems = document.querySelectorAll('.modal');
    var instances = M.Modal.init(elems);

    var forms = document.querySelectorAll('form[id^="edit_form_"], #location_form');
    forms.forEach(function(form) {
        const id = form.id;
        
        const fields = {
            latitude: document.getElementById("latitude-" + id),
            longitude: document.getElementById("longitude-" + id),
            altitude: document.getElementById("altitude-" + id),
            error_in_m: document.getElementById("error_in_m-" + id),
            name: document.getElementById("name-" + id)
        };

        Object.entries(fields).forEach(([fieldName, field]) => {
            if (field) {
                field.dataset.hasInteracted = 'false';
                
                field.addEventListener('input', function() {
                    this.dataset.hasInteracted = 'true';
                    if (fieldName !== 'name') {
                        updateDMSFields(
                            fieldName === 'latitude' ? this.value : null,
                            fieldName === 'longitude' ? this.value : null,
                            id
                        );
                        updateFieldValidation(this, fieldName, id);
                    }
                    checkFields(id);
                });

                field.addEventListener('focus', function() {
                    this.dataset.hasInteracted = 'true';
                });
            }
        });

        form.addEventListener('submit', function(e) {
            const allValid = checkFields(id);
            
            if (!allValid) {
                e.preventDefault();
                M.toast({html: 'Please fix the validation errors before saving', classes: 'red'});
                
                Object.entries(fields).forEach(([fieldName, field]) => {
                    if (field && fieldName !== 'name') {
                        updateFieldValidation(field, fieldName, id, true);
                    }
                });
            }
        });

        checkFields(id);
    });
});
</script>

% include("footer.tpl")