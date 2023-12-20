% include("header.tpl", title="Advanced")

<div id="error" class="error-message"></div>
<center>
    <div style="display: grid; grid-template-columns: repeat(4, 1fr); margin: 0.5rem; justify-content: center; gap: 0.5rem;">
        <button class="btn remote-button" onclick="buttonClicked(this, 'LOC')">GPS location lock</button>
        <button class="btn remote-button" onclick="buttonClicked(this, 'TIME')">GPS time lock</button>
    </div>
    <div style="display: flex; flex-direction: row; margin: 0px 5px 0px 5px; gap: 1rem; justify-content: center;">
    </div>
</center>
<script>

function buttonClicked(btn, code) {
    if(code == 'LOC') {
        fetch("/gps-lock")
        .then(response => {
            if (!response.ok) { throw Error(response.statusText); }
        })
    } else if(code == 'TIME') {
        fetch("/time-lock")
        .then(response => {
            if (!response.ok) { throw Error(response.statusText); }
        })
    }

}
</script>

% include("footer.tpl", title="PiFinder UI")

