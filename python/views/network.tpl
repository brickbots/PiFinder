% include("header.tpl", title="Network")
<h5 class="grey-text">Network Settings</h5>
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
<div class="row">
  <div class="col s10">
        <h5 class="grey-text">Wifi Networks</h5>
  </div>
  <div class="col s2">
    <a class="btn-floating btn-small grey"><i class="material-icons">add</i></a>
  </div>
</div>
<div class="card grey darken-2">
  <div class="card-content">
    <table class="grey-text">
% for network in net.get_wifi_networks():
% include("network_item", network=network)
% end
   </table>
  <div class="card-action">
    <a href="#" class="btn" onClick="">Save Changes</a>
  </div>
</div>
<script>
  document.addEventListener('DOMContentLoaded', function() {
      var elems = document.querySelectorAll('select');
          var instances = M.FormSelect.init(elems);
            });
</script>

% include("footer.tpl")

