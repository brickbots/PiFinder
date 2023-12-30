% include("header.tpl", title="Login")
<div class="row valign-wrapper" style="margin: 0px;">
  <div class="col s12">
        <h5 class="grey-text">Login Required</h5>
  </div>
</div>
% if defined("error_message"):
<div class="row">
  <div class="col s12">
    <p class="red-text">{{error_message}}
  </div>
</div>
% end
<div class="card grey darken-2">
  <form action="/login" method="post" id="login_form" class="col s12">
  <input type="hidden" name="origin_url" value="{{origin_url}}">
    <div class="card-content">
        <div class="row">
            <div class="input-field col s12">
                <input value="" id="password" type="password" name="password">
                <label for="password">Password</label>
            </div>
        </div>
    </div>
    <div class="card-action">
      <button type="submit" class="btn">Login</button>
    </div>
  </form>
</div>

% include("footer.tpl")

