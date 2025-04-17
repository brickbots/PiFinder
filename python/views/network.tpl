% include("header.tpl", title="Network")
<div class="row valign-wrapper" style="margin: 0px;">
  <div class="col s12">
        <h5 class="grey-text">Network Settings</h5>
  </div>
</div>
<div class="card grey darken-2">
  <div class="card-content">
    <form action="/network/update" method="post" id="network_form" class="col s12">
        <div class="row">
            <div class="input-field col s12">
                <select name="wifi_mode">
                    <option value="AP"
                    % if net.wifi_mode() == "AP":
                      selected
                    %end
                    >Access Point</option>
                    <option value="Client"
                    % if net.wifi_mode() == "Client":
                      selected
                    %end
                    >Client</option>
                </select>
                <label>Wifi Mode</label>
            </div>
        </div>
        <div class="row">
            <div class="input-field col s12">
                <input value="{{net.get_ap_name()}}" id="ap_name" type="text" name="ap_name">
                <label for="ap_name">Acess Point WiFi Name</label>
            </div>
        </div>
        % if not net.is_ap_open(): 
        <div class="row">
            <div class="input-field col s12">
                <input value="{{net.get_ap_pwd()}}" id="ap_passwd" type="password" name="ap_passwd">
                <label for="ap_passwd">Access Point WiFi Password</label>
                <p class="red-text">{{err_pwd}}</p>
            </div>
        </div>
        %end
        <div class="row">
            <div class="input-field col s12">
                <input value="{{net.get_ap_wifi_country()}}" id="wifi_country" type="text" name="wifi_country">
                <label for="wifi_country">Access Point WiFi Country</label>
                <p class="red-text">{{err_country}}</p>
            </div>
        </div>
        <div class="row">
            <div class="input-field col s12">
                <input value="{{net.get_host_name()}}" id="host_name" type="text" name="host_name">
                <label for="host_name">Host Name</label>
            </div>
        </div>
    </form>
  </div>
  <div class="card-action">
    <a href="#modal_restart" class="btn modal-trigger">Update and Restart</a>
  </div>
</div>
<div id="modal_restart" class="modal">
  <div class="modal-content">
    <h4>Save and Restart</h4>
    <p>This will update the network settings and restart the PiFinder. 
    You may have to adjust your network settings to re-connect.  Are you sure?</p>
  </div>
  <div class="modal-footer">
    <a href="#" onClick="document.getElementById('network_form').submit();" class="modal-close btn-flat">Do It</a>
    <a href="#!" class="modal-close btn-flat">Cancel</a>
  </div>
</div>
<div class="row valign-wrapper" style="margin: 0px;">
  <div class="col s10">
        <h5 class="grey-text">Wifi Networks</h5>
  </div>
  <div class="col s2">
% if not show_new_form:
    <a class="btn-floating btn-small grey" href="/network?add_new=1"><i class="material-icons">add</i></a>
% end
  </div>
</div>
<div class="card grey darken-2">
  <div class="card-content">
    <table class="grey-text">
% if show_new_form:
      <tr class="grey-text text-lighten-1">
        <td> 
        <form class="col s12" action="/network/add" method="post" id="new_network_form">
          <div class="row">
            <div class="input-field col s12">
              <input placeholder="SSID" id="ssid" type="text" name="ssid">
              <label for="ssid">Name</label>
            </div>
          </div>
          <div class="row">
            <div class="input-field col s12">
              <input placeholder="None" id="password" type="text" name="psk" class="validate" pattern=".{8,}">
              <label for="password">Password</label>
              <span class="helper-text" data-error="Too Short" data-success="">Min 8 Characters or leave None</span>

            </div>
          </div>
          <div class="row">
            <div class="input-field col s12">
              <a href="#" class="btn modal-trigger" onClick="document.getElementById('new_network_form').submit();">Save</a>
              &nbsp;
              <a href="/network" class="btn modal-trigger">Cancel</a>
            </div>
          </div>
        </form>
        </td>
      </tr>
% end
% for network in net.get_wifi_networks():
% include("network_item", network=network)
% end
   </table>
</div>
<script>
  document.addEventListener('DOMContentLoaded', function() {
      var elems = document.querySelectorAll('select');
          var instances = M.FormSelect.init(elems);
            });

document.addEventListener('DOMContentLoaded', function() {
    var elems = document.querySelectorAll('.modal');
        var instances = M.Modal.init(elems);
          });
</script>

% include("footer.tpl")

