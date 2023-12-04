% include("header.tpl", title="Restart")
<div class="row valign-wrapper" style="margin: 0px;">
  <div class="col s12 align-center">
        <h5 class="grey-text text-lighter-1">Restarting PiFinder</h5>
        <p class="grey-text">This will take approximately 20 seconds and you should
        be redirected to the home page.

        <p class="grey-text">If you are not automatically redirected <a href="/">Click Here</a>
  </div>
</div>
<div class="progress">
  <div class="indeterminate"></div>
</div>
<script>
setTimeout(function(){
    location.href="/";
    }, 20000); // 20000 milliseconds = 40 seconds

fetch("/system/restart_pifinder?" + new Date().getTime())
</script>

% include("footer.tpl", title="PiFinder UI")

