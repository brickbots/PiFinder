% include("header.tpl", title="Add eyepiece")

<div class="row valign-wrapper" style="margin: 0;">
    <div class="col s12">
% if eyepiece_id < 0:
            <h3 class="grey-text">Add a new eyepiece</h3>
% else:
            <h3 class="grey-text">Edit eyepiece</h3>
% end
    </div>
</div>

<form action="/equipment/add_eyepiece/{{eyepiece_id}}" method="post" id="add_eyepiece" class="col s12">
    <div class="row">
        <div class="input-field col s12">
            <input value="{{eyepiece.make}}" id="make" type="text" name="make">
            <label for="make">Make</label>
        </div>
    </div>
    <div class="row">
        <div class="input-field col s12">
            <input value="{{eyepiece.name}}" id="name" type="text" name="name">
            <label for="name">Name</label>
        </div>
    </div>
    <div class="row">
        <div class="input-field col s12">
            <input value="{{eyepiece.focal_length_mm}}" id="focal_length_mm" type="number" name="focal_length_mm">
            <label for="focal_length_mm">Focal Length (in mm)</label>
        </div>
    </div>
    <div class="row">
        <div class="input-field col s12">
            <input value="{{eyepiece.afov}}" id="afov" type="number" name="afov">
            <label for="afov">Apparent Field of View (in °)</label>
        </div>
    </div>
    <div class="row">
        <div class="input-field col s12">
            <input value="{{eyepiece.field_stop}}" id="field_stop" type="number" name="field_stop">
            <label for="field_stop">Field stop (in mm)</label>
        </div>
    </div>
</form>
<a href="#" onClick="document.getElementById('add_eyepiece').submit();"
   class="btn">

    % if eyepiece_id < 0:
    Add eyepiece!
    % else:
    Update eyepiece!
    % end
    </a>
<a href="/equipment" class="btn">Cancel</a>

<br />
<br />

% include("footer.tpl")
