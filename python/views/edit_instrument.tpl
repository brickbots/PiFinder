% include("header.tpl", title="Add instrument")

% if telescope.mount_type == "alt/az":
    % altaz_selected = "selected"
    % equatorial_selected = ""
% else:
    % altaz_selected = ""
    % equatorial_selected = "selected"
% end
% if telescope.flip_image:
    % flip_selected = "checked"
% else:
    % flip_selected = ""
% end
% if telescope.flop_image:
    % flop_selected = "checked"
% else:
    % flop_selected = ""
% end
% if telescope.reverse_arrow_a:
    % reverse_arrow_a_selected = "checked"
% else:
    % reverse_arrow_a_selected = ""
% end
% if telescope.reverse_arrow_b:
    % reverse_arrow_b_selected = "checked"
% else:
    % reverse_arrow_b_selected = ""
% end

<div class="row valign-wrapper" style="margin: 0;">
    <div class="col s12">
% if instrument_id < 0:
            <h3 class="grey-text">Add a new instrument</h3>
% else:
            <h3 class="grey-text">Edit instrument</h3>
% end
    </div>
</div>

% if defined("error_message"):
<div class="row">
    <div class="col s12">
        <p class="red-text">{{error_message}}
    </div>
</div>
% end

<form action="/equipment/add_instrument/{{instrument_id}}" method="post" id="add_instrument" class="col s12">
    <div class="row">
        <div class="row">
            <div class="input-field col s12">
                <input value="{{telescope.make}}" id="make" type="text" name="make">
                <label for="make">Make</label>
            </div>
        </div>
        <div class="row">
            <div class="input-field col s12">
                <input value="{{telescope.name}}" id="name" type="text" name="name">
                <label for="name">Instrument Name</label>
            </div>
        </div>
        <div class="row">
            <div class="input-field col s12">
                <input value="{{telescope.aperture_mm}}" id="aperture" type="number" name="aperture">
                <label for="aperture">Aperture (in mm)</label>
            </div>
        </div>
        <div class="row">
            <div class="input-field col s12">
                <input value="{{telescope.focal_length_mm}}" id="focal_length_mm" type="number" name="focal_length_mm">
                <label for="focal_length_mm">Focal Length (in mm)</label>
            </div>
        </div>
        <div class="row">
            <div class="input-field col s12">
                <input value="{{telescope.obstruction_perc}}" id="obstruction_perc" type="number" name="obstruction_perc">
                <label for="obstruction_perc">Obstruction %</label>
            </div>
        </div>
        <div class="row">
            <div class="input-field col s12">
                <select name="mount_type">
                    <option value="alt/az" {{altaz_selected}}>Alt/Az</option>
                    <option value="equatorial" {{equatorial_selected}}>Equatorial</option>
                </select>
                <label>
                    Mount Type
                </label>
            </div>
        </div>
        <div class="row">
            <div class="input-field col s12">
                <label>
                    <input type="checkbox" id="flip" {{flip_selected}} name="flip" />
                    <span>Flip image (upside down)</span>
                </label>
            </div>
        </div>
        <div class="row">
            <div class="input-field col s12">
                <label>
                    <input type="checkbox" id="flop" {{flop_selected}} name="flop" />
                    <span>Flop image (left right)</span>
                </label>
            </div>
        </div>
        <div class="row">
            <div class="input-field col s12">
                <label>
                    <input type="checkbox" id="reverse_arrow_a" {{reverse_arrow_a_selected}} name="reverse_arrow_a" />
                    <span>Reverse Arrow A</span>
                </label>
            </div>
        </div>
        <div class="row">
            <div class="input-field col s12">
                <label>
                    <input type="checkbox" id="reverse_arrow_b" {{reverse_arrow_b_selected}} name="reverse_arrow_b" />
                    <span>Reverse Arrow B</span>
                </label>
            </div>
        </div>
    </div>
</form>

<a href="#" onClick="document.getElementById('add_instrument').submit();"
   class="btn">

    % if instrument_id < 0:
    Add instrument!
    % else:
    Update instrument!
    % end
    </a>
<a href="/equipment" class="btn">Cancel</a>

<br />
<br />

<script>
    document.addEventListener('DOMContentLoaded', function () {
        let elems = document.querySelectorAll('select');
        let instances = M.FormSelect.init(elems);
    });
</script>

% include("footer.tpl")

