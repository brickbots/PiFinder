% include("header.tpl", title="Location Management")
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
      <form action="/locations/add" method="post" class="col s12">
        <div class="row">
          <div class="input-field col s12">
            <input id="name" type="text" name="name" required/>
            <label for="name">Location Name</label>
          </div>
        </div>
        <div class="row">
          <div class="input-field col s4">
            <input id="latitude" type="number" step="any" name="latitude" required/>
            <label for="latitude">Latitude (Decimal)</label>
          </div>
          <div class="input-field col s4">
            <input id="longitude" type="number" step="any" name="longitude" required/>
            <label for="longitude">Longitude (Decimal)</label>
          </div>
          <div class="input-field col s4">
            <input id="altitude" type="number" step="any" name="altitude" required/>
            <label for="altitude">Altitude (meters)</label>
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
            <button type="submit" class="waves-effect waves-light btn">Save Location</button>
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
                <a href="#rename-modal-{{ i }}" class="waves-effect waves-light btn-small modal-trigger" title="Rename">
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
    <h4>Rename Location</h4>
    <form action="/locations/rename/{{ i }}" method="post">
      <div class="input-field">
        <input id="rename-{{ i }}" type="text" name="name" value="{{ location.name }}" required/>
        <label for="rename-{{ i }}">New Name</label>
      </div>
      <div class="modal-footer">
        <button type="submit" class="waves-effect waves-light btn">Save</button>
        <a href="#!" class="modal-close waves-effect waves-light btn grey">Cancel</a>
      </div>
    </form>
  </div>
</div>
% end

<script>
document.addEventListener('DOMContentLoaded', function() {
    var elems = document.querySelectorAll('.modal');
    var instances = M.Modal.init(elems);
});
</script>

% include("footer.tpl") 