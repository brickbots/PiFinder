%if network["status"] == "new":
  <tr class="grey-text text-lighten-1">
    <td> 
    <form class="col s12" action="/network/add" method="post">
      <div class="row">
        <div class="input-field col s12">
          <input placeholder="SSID" id="ssid" type="text" class="validate">
          <label for="ssid">Network Name</label>
        </div>
      </div>
    </form>
    </td>
    <td>
      <a href="/network" class="grey-text"><i class="material-icons">cancel</i></a>
      <a href="/network" class="grey-text"><i class="material-icons">save</i></a>
    </td>
  </tr>
%else:
  <tr
  %if network["status"] == "deleted":
  class="grey darken-3 grey-text text-darken-1"
  %else:
  class="grey-text text-lighten-1"
  %end
   >
      <td>
          <h5>{{network["ssid"]}}</h5>
          Security: <b>{{network["key_mgmt"]}}</b>
      </td>
  %if network["status"] != "deleted":
      <td><a href="/network/delete/{{network["id"]}}" class="grey-text"><i class="material-icons">delete</i></a></td>
  %else:
      <td><a href="/network/undelete/{{network["id"]}}" class="grey-text"><i class="material-icons">restore</i></a></td>
  %end
  </tr>
%end
