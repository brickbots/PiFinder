% include("header.tpl", title="Restart")
<div class="row valign-wrapper" style="margin: 0px;">
  <div class="col s12 align-center">
        <h5 class="grey-text text-lighter-1">Restarting System</h5>
        <p class="grey-text">This will take approximately 45 seconds and you should
        be redirected to the home page.

        <p class="grey-text text-lighter-1">You may need to change the URL above or connect to a differnet
        wifi network on your phone/tablet/computer depending on the changes you made to the PiFinder 
        configuration.  

        <p class="grey-text">If you are not automatically redirected <a href="/">Click Here</a>
  </div>
</div>
<div class="progress">
  <div class="indeterminate"></div>
</div>
<script>
setTimeout(function(){
    location.href="/";
    }, 40000); // 40000 milliseconds = 40 seconds

fetch("/system/restart?" + new Date().getTime())
</script>

% include("footer.tpl", title="PiFinder UI")

