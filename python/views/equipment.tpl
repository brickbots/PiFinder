% include("header.tpl", title="Equipment")
<div class="row valign-wrapper" style="margin: 0;">
    <div class="col s12">
        <h3 class="grey-text">Equipment</h3>
    </div>
</div>

% if defined("error_message"):
<div class="row">
    <div class="col s12">
        <p class="red-text">{{error_message}}
    </div>
</div>
% end

% if defined("success_message"):
<div class="row">
    <div class="col s12">
        <p class="green-text">{{success_message}}
    </div>
</div>
% end

<div class="row">
    <div class="col s3 center-align grey-text">
        <h6 class="grey-text text-lighten-1">Instruments</h6>
            {{len(equipment.telescopes)}}
    </div>
    <div class="col s3 center-align grey-text">
        <h6 class="grey-text text-lighten-1">Eyepieces</h6>
            {{len(equipment.eyepieces)}}
    </div>
    <div class="col s3 center-align grey-text">
        <h6 class="grey-text text-lighten-1">Import from DeepskyLog</h6>
        <a href="#modal_import_from_deepskylog" class="modal-trigger"><i
                    class="material-icons small">download</i></a>
    </div>
</div>

<div id="modal_import_from_deepskylog" class="modal">
    <div class="modal-content">
        <h4>Download instruments from DeepskyLog</h4>
        <p>This will delete all instruments and eyepieces from your PiFinder and replace them
            with the instruments and eyepieces from DeepskyLog. Are you really sure?</p>
        <form action="/equipment/import_from_deepskylog" method="post" id="deepskylog_form" class="col s12">
            <div class="row">
                <div class="input-field col s12">
                    <input value="" id="dsl_name" type="text" name="dsl_name">
                    <label for="dsl_name">DeepskyLog User Name</label>
                </div>
            </div>
        </form>
    </div>
    <div class="modal-footer">
        <a href="#" onClick="document.getElementById('deepskylog_form').submit();"
           class="modal-close btn-flat">Import!</a>
        <a href="#!" class="modal-close btn-flat">Cancel</a>
    </div>
</div>

<a href="/equipment/edit_instrument/-1" class="btn modal-trigger">Add new instrument</a>
<a href="/equipment/edit_eyepiece/-1" class="btn modal-trigger">Add new eyepiece</a>


<h5 class="grey-text">Instruments</h5>
<table class="grey darken-2 grey-text z-depth-1">
    <tr>
        <th>Make</th>
        <th>Name</th>
        <th>Aperture</th>
        <th>Focal Length (mm)</th>
        <th>Obstruction %</th>
        <th>Mount Type</th>
        <th>Flip</th>
        <th>Flop</th>
        <th>Reverse Arrow A</th>
        <th>Reverse Arrow B</th>
        <th>Active</th>
        <th>Actions</th>
    </tr>
    % for instrument in equipment.telescopes:
    <tr>
        <td>{{instrument.make}}</td>
        <td>{{instrument.name}}</td>
        <td>{{instrument.aperture_mm}}</td>
        <td>{{instrument.focal_length_mm}}</td>
        <td>{{instrument.obstruction_perc}}</td>
        <td>{{instrument.mount_type}}</td>
        <td>{{instrument.flip_image}}</td>
        <td>{{instrument.flop_image}}</td>
        <td>{{instrument.reverse_arrow_a}}</td>
        <td>{{instrument.reverse_arrow_b}}</td>
        <td>
                <label>
                    <a href="/equipment/set_active_instrument/{{equipment.telescopes.index(instrument)}}">
                        <input type="radio"
                        % if equipment.active_telescope == instrument:
                            checked
                        % end
                        />
                        <span></span>
                    </a>
                </label>
        </td>
        <td>
            <a href="/equipment/edit_instrument/{{equipment.telescopes.index(instrument)}}"><i class="material-icons">edit</i></a>
            <a href="/equipment/delete_instrument/{{equipment.telescopes.index(instrument)}}"><i class="material-icons">delete</i></a>
       </td>
    </tr>
    % end
</table>

<h5 class="grey-text">Eyepieces <span class="grey-text text-lighten-1" style="font-size: 14px;">(drag to reorder)</span></h5>
<table class="grey darken-2 grey-text z-depth-1">
    <thead>
        <tr>
            <th style="width: 30px;"></th>
            <th>Make</th>
            <th>Name</th>
            <th>Focal Length (mm)</th>
            <th>Apparent FOV</th>
            <th>Field Stop</th>
            <th>Active</th>
            <th>Actions</th>
        </tr>
    </thead>
    <tbody id="eyepiece-list">
    % for eyepiece in equipment.eyepieces:
    <tr data-eyepiece-index="{{equipment.eyepieces.index(eyepiece)}}" style="cursor: move;">
        <td class="drag-handle"><i class="material-icons grey-text text-lighten-1">drag_indicator</i></td>
        <td>{{eyepiece.make}}</td>
        <td>{{eyepiece.name}}</td>
        <td>{{eyepiece.focal_length_mm}}</td>
        <td>{{eyepiece.afov}}</td>
        <td>{{eyepiece.field_stop}}</td>
        <td>
                <label>
                    <a href="/equipment/set_active_eyepiece/{{equipment.eyepieces.index(eyepiece)}}">
                        <input type="radio"
                        % if equipment.active_eyepiece == eyepiece:
                            checked
                        % end
                        />
                        <span></span>
                    </a>
                </label>
        </td>
        <td>
            <a href="/equipment/edit_eyepiece/{{equipment.eyepieces.index(eyepiece)}}"><i class="material-icons">edit</i></a>
            <a href="/equipment/delete_eyepiece/{{equipment.eyepieces.index(eyepiece)}}"><i class="material-icons">delete</i></a>
        </td>
    </tr>
    % end
    </tbody>
</table>

<br/>

<script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.0/Sortable.min.js"></script>
<script>
    document.addEventListener('DOMContentLoaded', function () {
        let elems = document.querySelectorAll('select');
        let instances = M.FormSelect.init(elems);
    });

    document.addEventListener('DOMContentLoaded', function () {
        let elems = document.querySelectorAll('.modal');
        let instances = M.Modal.init(elems);
    });

    function set_instrument_id(id) {
        let instrument_id = id;
    }

    // Initialize drag-and-drop for eyepieces
    document.addEventListener('DOMContentLoaded', function () {
        const eyepieceList = document.getElementById('eyepiece-list');
        if (eyepieceList) {
            Sortable.create(eyepieceList, {
                handle: '.drag-handle',
                animation: 150,
                ghostClass: 'grey',
                onEnd: function (evt) {
                    // Get the new order of eyepiece indices
                    const rows = eyepieceList.querySelectorAll('tr');
                    const newOrder = Array.from(rows).map(row =>
                        parseInt(row.getAttribute('data-eyepiece-index'))
                    );

                    // Send the new order to the server
                    fetch('/equipment/reorder_eyepieces', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ order: newOrder })
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            console.log('Eyepiece order saved successfully');
                            // Update the data-eyepiece-index attributes to reflect new positions
                            rows.forEach((row, index) => {
                                row.setAttribute('data-eyepiece-index', index);
                            });
                        } else {
                            console.error('Failed to save eyepiece order');
                            M.toast({html: 'Failed to save eyepiece order', classes: 'red'});
                        }
                    })
                    .catch(error => {
                        console.error('Error saving eyepiece order:', error);
                        M.toast({html: 'Error saving eyepiece order', classes: 'red'});
                    });
                }
            });
        }
    });
</script>

% include("footer.tpl")

