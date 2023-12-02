% include("header.tpl", title="Observing Sessions")
<h5 class=grey-text">Observing Sessions</h5>
<center>
<table class="grey darken-2 grey-text z-depth-1">
<tr>
<th>Date</th><th>Location</th><th>Objects</th>
</tr>
<tr>
    <td>
      <i class="material-icons medium">wifi</i>
    </td>
    <td class="grey-text text-lighten-1">{{wifi_mode}} Mode<br>{{network_name}}<br>{{ip}}</td>
    <td><a href="/network" class="grey-text"><i class="material-icons">edit</i></a></td>
</tr>
<tr>
    <td>
      <i class="material-icons medium">{{gps_icon}}</i>
    </td>
    <td class="grey-text text-lighten-1">{{gps_text}}<br>lat: {{lat_text}} / lon: {{lon_text}}</td>
    <td></td>
</tr>
<tr>
    <td>
      <i class="material-icons medium">{{camera_icon}}</i>
    </td>
    <td class="grey-text text-lighten-1">Sky Position<br>RA: {{ra_text}} / DEC: {{dec_text}}</td>
    <td></td>
</tr>
<tr>
    <td>
      <i class="material-icons medium">sd_card</i>
    </td>
    <td class="grey-text text-lighten-1">Software Version<br>{{software_version}}</td>
    <td></td>
</tr>
</table>
</center>

% include("footer.tpl")

