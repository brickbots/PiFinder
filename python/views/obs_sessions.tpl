% include("header.tpl", title="Observing Sessions")
<h5 class="grey-text">Observing Sessions</h5>
<div class="row">
  <div class="col s4 center-align grey-text">
    <h6 class="grey-text text-lighten-1">Sessions</h6>
    {{metadata["sess_count"]}}
  </div>
  <div class="col s4 center-align grey-text">
    <h6 class="grey-text text-lighten-1">Objects</h6>
    {{metadata["object_count"]}}
  </div>
  <div class="col s4 center-align grey-text">
    <h6 class="grey-text text-lighten-1">Total Hours</h6>
    {{round(metadata["total_duration"], 1)}}
  </div>
</div>
<center>
<table class="grey darken-2 grey-text z-depth-1">
<tr>
<th>Date</th><th>Location</th><th>Objects</th>
</tr>
</table>
</center>

% include("footer.tpl")

