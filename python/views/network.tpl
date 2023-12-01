% include("header.tpl", title="Network")
<div class="row valign-wrapper" style="margin: 0px;">
  <div class="col s12">
        <h5 class="grey-text">Network Settings</h5>
  </div>
</div>
<div class="card grey darken-2">
  <div class="card-content">
    <form action="/network_update" method="post" id="network_form" class="col s12">
        <div class="row">
            <div class="input-field col s12">
                <select>
                    <option value="ap"
                    % if net.wifi_mode() == "AP":
                      selected
                    %end
                    >Access Point</option>
                    <option value="cli"
                    % if net.wifi_mode() == "Cli":
                      selected
                    %end
                    >Client</option>
                </select>
                <label>Wifi Mode</label>
            </div>
        </div>
        <div class="row">
            <div class="input-field col s12">
                <input placeholder="{{net.get_ap_name()}}" id="ap_name" type="text">
                <label for="host_name">AP Network Name</label>
            </div>
        </div>
        <div class="row">
            <div class="input-field col s12">
                <input placeholder="{{net.get_host_name()}}" id="host_name" type="text">
                <label for="host_name">Host Name</label>
            </div>
        </div>
    </form>
  </div>
  <div class="card-action">
    <a href="#" class="btn" onClick="document.getElementById('network_form').submit();">Update and Restart</a>
  </div>
</div>
<div class="row valign-wrapper" style="margin: 0px;">
  <div class="col s10">
        <h5 class="grey-text">Wifi Networks</h5>
  </div>
  <div class="col s2">
    <a class="btn-floating btn-small grey" href="/network?add_new=1"><i class="material-icons">add</i></a>
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
              <input placeholder="SSID" id="ssid" type="text">
              <label for="ssid">Name</label>
            </div>
          </div>
          <div class="row">
            <div class="input-field col s12">
              <input placeholder="None" id="password" type="text">
              <label for="password">Password</label>
            </div>
          </div>
        </form>
        </td>
        <td>
          <a href="/network" class="grey-text"><i class="material-icons">cancel</i></a>
          <a href="#" class="grey-text" onClick="document.getElementById('new_network_form').submit();"><i class="material-icons">save</i></a>
        </td>
      </tr>
% end
% for network in net.get_wifi_networks():
% include("network_item", network=network)
% end
   </table>
  <div class="card-action">
    <a href="/network/save" class="btn">Save Changes</a>
  </div>
</div>
<script>
  document.addEventListener('DOMContentLoaded', function() {
      var elems = document.querySelectorAll('select');
          var instances = M.FormSelect.init(elems);
            });
</script>

% include("footer.tpl")

