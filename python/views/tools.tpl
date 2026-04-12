% include("header.tpl", title="Tools")
<div class="row valign-wrapper" style="margin: 0px;">
  <div class="col s12">
        <h3 class="grey-text">Tools</h3>
  </div>
</div>
% if defined("status_message"):
<div class="row">
  <div class="col s12">
    <p class="grey-text"><b>{{status_message}}</b>
  </div>
</div>
% end
% if defined("error_message"):
<div class="row">
  <div class="col s12">
    <p class="red-text">{{error_message}}
  </div>
</div>
% end
<div class="card grey darken-2">
  <div class="card-content">
    <h5 class="grey-text">Change Password</h5>
    <div class="row">
        <p class="grey-text">This will change the password for this web interface
        and the user account pifinder for ssh and other tools
    </div>
    <form action="/tools/pwchange" method="post" id="pwchange_form" class="col s12"> 
        <div class="row">
                <div class="input-field col s12">
                    <input value="" id="current_password" type="password" name="current_password">
                    <label for="current_password">Current Password</label>
                </div>
                <div class="input-field col s12">
                    <input value="" id="new_passworda" type="password" name="new_passworda">
                    <label for="new_passworda">New Password</label>
                </div>
                <div class="input-field col s12">
                    <input value="" id="new_passwordb" type="password" name="new_passwordb">
                    <label for="new_passwordb">Re-Enter New Password</label>
                </div>
        </div>
        <div class="row">
            <div class="card-action">
              <button type="submit" class="btn">Change Password</button>
            </div>
        </div>
    </form>
  </div>
</div>
<div class="card grey darken-2">
  <div class="card-content">
    <h5 class="grey-text">User Data and Settings</h5>
    <div class="row">
        <p class="grey-text">You can download a zip file of all your personal settings, observations
        and observing lists for safe keeping.
    </div>
    <div class="row">
        <a href="/tools/backup" class="btn modal-trigger">Download Backup File</a>
    </div>
    <div class="row">
        <hr>
    </div>
    <div class="row">
        <p class="grey-text">To restore a previously downloaded backup, upload it below
        <form action="/tools/restore" method="post" id="restore_form" class="col s12" enctype="multipart/form-data">
            <div class="file-field input-field">
                <div class="btn grey lighten-2 grey-text text-darken-3">
                    <span>Choose file</span>
                    <input name="backup_file" type="file" />
                    </div>
                    <div class="file-path-wrapper">
                    <input class="file-path validate" type="text"
                        placeholder="Select backup file to restore"
                    />
                </div>
            </div>
        </form>
    </div>
    <div class="row">
        <a href="#modal_restore" class="btn modal-trigger">Upload and Restore</a>
    </div>
  </div>
</div>
<div id="modal_restore" class="modal">
  <div class="modal-content">
    <h4>Restore User Data</h4>
    <p>This will use the provided file to restore your user data.  This will overwrite any existing
    preferences and observations. Are you sure?</p>
  </div>
  <div class="modal-footer">
    <a href="#" onClick="document.getElementById('restore_form').submit();" class="modal-close btn-flat">Do It</a>
    <a href="#!" class="modal-close btn-flat">Cancel</a>
  </div>
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

