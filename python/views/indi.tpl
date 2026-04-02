% include("header.tpl", title="INDI Mount Control")

<div class="row">
  <div class="col s12">
    <h5 class="grey-text text-lighten-1">INDI Mount Control</h5>
  </div>
</div>

% if defined('copy_message'):
  % if copy_success:
<div class="row">
  <div class="col s12">
    <div class="card green darken-3">
      <div class="card-content white-text">
        <i class="material-icons left">check_circle</i> {{copy_message}}
      </div>
    </div>
  </div>
</div>
  % else:
<div class="row">
  <div class="col s12">
    <div class="card red darken-3">
      <div class="card-content white-text">
        <i class="material-icons left">error</i> {{copy_message}}
      </div>
    </div>
  </div>
</div>
  % end
% end

<!-- ================================================================ -->
<!-- INDI Server Status -->
<!-- ================================================================ -->
<div class="row">
  <div class="col s12">
    <div class="card grey darken-2">
      <div class="card-content">
        <span class="card-title grey-text text-lighten-1">
          <i class="material-icons left">settings_ethernet</i>INDI Server
        </span>
        <table class="grey darken-3 grey-text">
          <tbody>
            <tr>
              <td>Connection</td>
              <td>
                % if status.get('indi_connected'):
                <span class="green-text"><i class="material-icons tiny">check_circle</i> Connected</span>
                % elif status.get('state') == 'waiting_for_indi':
                <span class="orange-text"><i class="material-icons tiny">hourglass_empty</i> Waiting…</span>
                % elif status.get('state') == 'indi_unavailable':
                <span class="red-text"><i class="material-icons tiny">cancel</i> Unavailable</span>
                % elif status.get('state') == 'not_started':
                <span class="grey-text"><i class="material-icons tiny">radio_button_unchecked</i> Not started</span>
                % else:
                <span class="grey-text"><i class="material-icons tiny">help_outline</i> {{status.get('state','unknown')}}</span>
                % end
              </td>
            </tr>
            <tr>
              <td>Server</td>
              <td class="grey-text text-lighten-1">{{status.get('indi_host','localhost')}}:{{status.get('indi_port',7624)}}</td>
            </tr>
            % if status.get('timestamp'):
            <tr>
              <td>Last check</td>
              <td class="grey-text text-lighten-1">{{status.get('timestamp','')}}</td>
            </tr>
            % end
          </tbody>
        </table>

        % if status.get('devices'):
        <br>
        <p class="grey-text text-lighten-1"><strong>Detected INDI devices:</strong></p>
        <ul class="collection grey darken-3" style="border:none">
          % for dev in status.get('devices', []):
          <li class="collection-item grey darken-3 grey-text text-lighten-1">
            <i class="material-icons tiny">satellite_alt</i> {{dev}}
          </li>
          % end
        </ul>
        % end

      </div>
    </div>
  </div>
</div>

<!-- ================================================================ -->
<!-- Alignment Subsystem per Driver -->
<!-- ================================================================ -->
<div class="row">
  <div class="col s12">
    <div class="card grey darken-2">
      <div class="card-content">
        <span class="card-title grey-text text-lighten-1">
          <i class="material-icons left">my_location</i>Alignment Subsystem Status
        </span>

        % drivers = status.get('drivers', {})
        % if not drivers:
        <p class="grey-text">No driver data available — INDI check has not run yet or no devices were found.</p>
        % else:
        % for key, drv in drivers.items():
        <div class="card grey darken-3" style="margin-bottom:8px">
          <div class="card-content">
            <span class="card-title grey-text text-lighten-1" style="font-size:1rem">
              {{drv.get('description', key)}}
              <span class="grey-text" style="font-size:0.8rem"> — <em>{{drv.get('device_name','')}}</em></span>
            </span>

            <table class="grey-text" style="font-size:0.9rem">
              <tbody>
                <tr>
                  <td style="width:40%">Device present</td>
                  <td>
                    % if drv.get('device_found'):
                    <span class="green-text"><i class="material-icons tiny">check</i> Yes</span>
                    % else:
                    <span class="grey-text text-darken-1"><i class="material-icons tiny">remove</i> Not connected</span>
                    % end
                  </td>
                </tr>
                % if drv.get('device_found'):
                <tr>
                  <td>Alignment subsystem detected</td>
                  <td>
                    % if drv.get('alignment_detected'):
                      % if drv.get('alignment_active'):
                      <span class="orange-text"><i class="material-icons tiny">warning</i> Active</span>
                      % else:
                      <span class="green-text"><i class="material-icons tiny">check_circle</i> Present but inactive</span>
                      % end
                    % else:
                    <span class="grey-text"><i class="material-icons tiny">not_interested</i> Not detected</span>
                    % end
                  </td>
                </tr>
                % if drv.get('alignment_active'):
                <tr>
                  <td>Will disable</td>
                  <td>
                    % if drv.get('will_disable'):
                    <span class="green-text"><i class="material-icons tiny">check_circle</i> Yes</span>
                    % else:
                    <span class="orange-text"><i class="material-icons tiny">warning</i> No (no disable commands configured)</span>
                    % end
                  </td>
                </tr>
                <tr>
                  <td>Disable result</td>
                  <td>
                    % if drv.get('disabled'):
                    <span class="green-text"><i class="material-icons tiny">check_circle</i> Disabled successfully</span>
                    % elif drv.get('will_disable'):
                    <span class="red-text"><i class="material-icons tiny">error</i> Failed</span>
                    % else:
                    <span class="orange-text"><i class="material-icons tiny">do_not_disturb</i> Skipped (alignment remains active)</span>
                    % end
                  </td>
                </tr>
                % end
                % end
              </tbody>
            </table>

            % cmds = drv.get('commands_sent', [])
            % if cmds:
            <p class="grey-text text-lighten-1" style="margin-top:8px"><strong>Commands sent:</strong></p>
            <ul>
              % for cmd in cmds:
              <li class="grey-text text-lighten-1" style="font-size:0.85rem">
                % if cmd.get('success'):
                <i class="material-icons tiny green-text">check</i>
                % else:
                <i class="material-icons tiny red-text">close</i>
                % end
                <code>{{cmd.get('property','')}}.{{cmd.get('element','')}} = {{cmd.get('value','')}}</code>
              </li>
              % end
            </ul>
            % end

            % errs = drv.get('errors', [])
            % if errs:
            <p class="red-text" style="margin-top:4px"><strong>Errors:</strong></p>
            <ul>
              % for err in errs:
              <li class="red-text text-lighten-1" style="font-size:0.85rem">{{err}}</li>
              % end
            </ul>
            % end

          </div>
        </div>
        % end
        % end

        % global_errors = status.get('errors', [])
        % if global_errors:
        <div class="card red darken-3" style="margin-top:8px">
          <div class="card-content white-text">
            <span class="card-title">Global Errors</span>
            <ul>
              % for err in global_errors:
              <li>{{err}}</li>
              % end
            </ul>
          </div>
        </div>
        % end

      </div>
    </div>
  </div>
</div>

<!-- ================================================================ -->
<!-- Config File Management -->
<!-- ================================================================ -->
<div class="row">
  <div class="col s12">
    <div class="card grey darken-2">
      <div class="card-content">
        <span class="card-title grey-text text-lighten-1">
          <i class="material-icons left">description</i>Alignment Configuration File
        </span>
        <p class="grey-text text-lighten-1">
          <strong>Repository config:</strong> <code>{{repo_config_path}}</code><br>
          <strong>User override:</strong> <code>{{user_config_path}}</code>
        </p>

        % if user_config_exists:
          % if user_config_modified:
          <div class="card orange darken-4" style="margin-bottom:8px">
            <div class="card-content white-text">
              <i class="material-icons left">warning</i>
              The user override file differs from the repository version (see diff below).
              Copying will overwrite your customisations.
            </div>
          </div>
          <p class="grey-text text-lighten-1"><strong>Diff (repo → user):</strong></p>
          <pre class="grey darken-4 grey-text text-lighten-1"
               style="overflow-x:auto; font-size:0.8rem; padding:8px; border-radius:4px">% for line in diff_lines:
% stripped = line.rstrip('\n')
% if stripped.startswith('+'):
<span class="green-text">{{stripped}}</span>
% elif stripped.startswith('-'):
<span class="red-text">{{stripped}}</span>
% elif stripped.startswith('@@'):
<span class="cyan-text">{{stripped}}</span>
% else:
{{stripped}}
% end
% end</pre>
          % else:
          <p class="green-text"><i class="material-icons tiny">check_circle</i> User override is identical to the repository version.</p>
          % end
        % else:
        <p class="grey-text text-lighten-1">No user override file exists. The repository defaults are used.</p>
        % end

        <form action="/indi/copy_config" method="post" style="margin-top:16px"
              % if user_config_modified:
              onsubmit="return confirm('The user override file has local changes. Overwrite with the repository version?');"
              % end
        >
          <button type="submit" class="btn waves-effect waves-light
            % if user_config_modified:
            orange darken-2
            % else:
            blue darken-2
            % end
          ">
            <i class="material-icons left">file_copy</i>
            % if user_config_exists:
            Reset user config to repository defaults
            % else:
            Copy repository config to user directory
            % end
          </button>
        </form>

      </div>
    </div>
  </div>
</div>

<!-- ================================================================ -->
<!-- Raw JSON status (collapsible) -->
<!-- ================================================================ -->
<div class="row">
  <div class="col s12">
    <ul class="collapsible grey darken-2">
      <li>
        <div class="collapsible-header grey darken-2 grey-text text-lighten-1">
          <i class="material-icons">code</i>Raw INDI Status JSON
        </div>
        <div class="collapsible-body grey darken-3">
          <pre class="grey-text text-lighten-1" style="font-size:0.8rem; overflow-x:auto">
% import json
{{json.dumps(status, indent=2, default=str)}}
          </pre>
          <p><a href="/indi/status.json" class="grey-text text-lighten-1" target="_blank">
            <i class="material-icons tiny">open_in_new</i> Open as JSON</a></p>
        </div>
      </li>
    </ul>
  </div>
</div>

% include("footer.tpl")
