% include("header.tpl", title="Observing Session")
<h5 class="grey-text">Observing Session {{session["UID"]}}</h5>
<div class="row">
  <div class="col s4 center-align grey-text">
    <h6 class="grey-text text-lighten-1">Objects</h6>
    {{session["observations"]}}
  </div>
  <div class="col s4 center-align grey-text">
    <h6 class="grey-text text-lighten-1">Hours</h6>
    {{round(session["duration"], 1)}}
  </div>
  <div class="col s4">
    <a href="/observations/{{session["UID"]}}?download=1" class="grey-text"><i class="material-icons medium">download</i></a>
  </div>
</div>
<center>
<table class="grey darken-2 grey-text z-depth-1">
<tr>
<th>Time</th><th>Catalog</th><th>Sequence</th><th>Notes</th>
</tr>
% for object in objects:
<tr>
  <td>{{object["obs_time_local"]}}</td>
  <td>{{object["catalog"]}}</td>
  <td>{{object["sequence"]}}</td>
  <td>{{!object["notes"]}}</td>
</tr>
% end
</table>
</center>

% include("footer.tpl")

