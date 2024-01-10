  <tr class="grey-text text-lighten-1">
      <td>
          <h5>{{network["ssid"]}}</h5>
          Security: <b>{{network["key_mgmt"]}}</b>
      </td>
      <td>
        <a href="#modal{{network["UUID"]}}" class="grey-text modal-trigger">
          <i class="material-icons">delete</i>
        </a>
      </td>
  </tr>
  <div id="modal{{network["UUID"]}}" class="modal">
    <div class="modal-content">
      <h4>Delete {{network["ssid"]}}</h4>
      <p>This will take effect immediately and can not be undone.  Are you sure?</p>
    </div>
    <div class="modal-footer">
      <a href="/network/delete/{{network["UUID"]}}" class="modal-close btn-flat">Delete</a>
      <a href="#!" class="modal-close btn-flat">Cancel</a>
    </div>
  </div>
