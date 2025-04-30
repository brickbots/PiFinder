<div class="row">
  <form action="{{ action }}" method="post" class="col s12" id="{{ form_id }}">
    <div class="row">
      <div class="input-field col s12">
        <input id="name-{{ form_id }}" type="text" name="name" value="{{ name }}" required/>
        <label for="name-{{ form_id }}">Location Name</label>
      </div>
    </div>
    <div class="row">
      <div class="input-field col s12">
        <label>
          <input type="checkbox" id="formatSwitch-{{ form_id }}" onclick="toggleFormat('{{ form_id }}')"/>
          <span>Use DMS Format</span>
        </label>
      </div>
    </div>
    <div class="row" id="decimalFormat-{{ form_id }}">
      <div class="input-field col s4">
        <input id="latitude-{{ form_id }}" type="number" step="any" name="latitude" value="{{ latitude }}" required/>
        <label for="latitude-{{ form_id }}">Latitude (Decimal)</label>
        <span class="helper-text"></span>
      </div>
      <div class="input-field col s4">
        <input id="longitude-{{ form_id }}" type="number" step="any" name="longitude" value="{{ longitude }}" required/>
        <label for="longitude-{{ form_id }}">Longitude (Decimal)</label>
        <span class="helper-text"></span>
      </div>
      <div class="input-field col s4">
        <input id="altitude-{{ form_id }}" type="number" step="any" name="altitude" value="{{ altitude }}" required/>
        <label for="altitude-{{ form_id }}">Altitude (meters)</label>
        <span class="helper-text"></span>
      </div>
    </div>
    <div class="row" id="dmsFormat-{{ form_id }}" style="display:none;">
      <div class="input-field col s4">
        <input id="latitudeD-{{ form_id }}" type="number" name="latitudeD"/>
        <label for="latitudeD-{{ form_id }}">Latitude Degrees</label>
      </div>
      <div class="input-field col s4">
        <input id="latitudeM-{{ form_id }}" type="number" name="latitudeM"/>
        <label for="latitudeM-{{ form_id }}">Latitude Minutes</label>
      </div>
      <div class="input-field col s4">
        <input id="latitudeS-{{ form_id }}" type="number" name="latitudeS"/>
        <label for="latitudeS-{{ form_id }}">Latitude Seconds</label>
      </div>
      <div class="input-field col s4">
        <input id="longitudeD-{{ form_id }}" type="number" name="longitudeD"/>
        <label for="longitudeD-{{ form_id }}">Longitude Degrees</label>
      </div>
      <div class="input-field col s4">
        <input id="longitudeM-{{ form_id }}" type="number" name="longitudeM"/>
        <label for="longitudeM-{{ form_id }}">Longitude Minutes</label>
      </div>
      <div class="input-field col s4">
        <input id="longitudeS-{{ form_id }}" type="number" name="longitudeS"/>
        <label for="longitudeS-{{ form_id }}">Longitude Seconds</label>
      </div>
    </div>
    <div class="row">
      <div class="input-field col s6">
        <input id="error_in_m-{{ form_id }}" type="number" step="any" name="error_in_m" value="{{ error_in_m }}"/>
        <label for="error_in_m-{{ form_id }}">Error (meters)</label>
        <span class="helper-text"></span>
      </div>
      <div class="input-field col s6">
        <input id="source-{{ form_id }}" type="text" name="source" value="{{ source }}"/>
        <label for="source-{{ form_id }}">Source</label>
      </div>
    </div>
    <div class="row">
      <div class="col s12">
        <button type="submit" id="saveButton-{{ form_id }}" class="waves-effect waves-light btn">{{ submit_text }}</button>
        <a href="{{ cancel_url }}" class="waves-effect waves-light btn grey {{ cancel_class }}">Cancel</a>
      </div>
    </div>
  </form>
</div>