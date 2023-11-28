% include("header.tpl", title="Remote")

<div id="error" class="error-message"></div>
<div class="center-align">
    <img id="image" src="" alt="PiFinder Screen" class="pifinder-screen z-depth-2">
</div>
<center>
    <div style="display: grid; grid-template-columns: repeat(4, 1fr); margin: 0.5rem; justify-content: center; gap: 0.5rem;">
        <button class="btn remote-button" onclick="buttonClicked(this, 'A')">A</button>
        <button class="btn remote-button" onclick="buttonClicked(this, 'B')">B</button>
        <button class="btn remote-button" onclick="buttonClicked(this, 'C')">C</button>
        <button class="btn remote-button" onclick="buttonClicked(this, 'D')">D</button>
        <button class="btn remote-button" onclick="buttonClicked(this, '1')">1</button>
        <button class="btn remote-button" onclick="buttonClicked(this, '2')">2</button>
        <button class="btn remote-button" onclick="buttonClicked(this, '3')">3</button>
        <button class="btn remote-button" onclick="buttonClicked(this, 'UP')">Up</button>
        <button class="btn remote-button" onclick="buttonClicked(this, '4')">4</button>
        <button class="btn remote-button" onclick="buttonClicked(this, '5')">5</button>
        <button class="btn remote-button" onclick="buttonClicked(this, '6')">6</button>
        <button class="btn remote-button" onclick="buttonClicked(this, 'DN')">Down</button>
        <button class="btn remote-button" onclick="buttonClicked(this, '7')">7</button>
        <button class="btn remote-button" onclick="buttonClicked(this, '8')">8</button>
        <button class="btn remote-button" onclick="buttonClicked(this, '9')">9</button>
        <button class="btn remote-button" onclick="buttonClicked(this, 'ENT')">Enter</button>
        <button class="btn remote-button" id="altButton" onclick="buttonPressed(this)">Ent+</button>
        <button class="btn remote-button" onclick="buttonClicked(this, '0')">0</button>
        <button class="btn remote-button" id="longButton" onclick="buttonPressed(this)">Long</button>
    </div>
    <div style="display: flex; flex-direction: row; margin: 0px 5px 0px 5px; gap: 1rem; justify-content: center;">
    </div>
</center>
<script>
function fetchImage() {
    const imageElement = document.getElementById('image');
    fetch("/image?t=" + new Date().getTime())
        .then(response => {
            if (!response.ok) { throw Error(response.statusText); }
            return response.blob();
        })
        .then(imageBlob => {
            let imageObjectURL = URL.createObjectURL(imageBlob);
            imageElement.src = imageObjectURL;
            // When the image can't be fetched, display a static message
            const errorElement = document.getElementById('error');
            errorElement.innerHTML = "";
        })
        .catch(error => {
            console.log(error);
            // When the image can't be fetched, display a static message
            const errorElement = document.getElementById('error');
            errorElement.innerHTML = "PiFinder server is currently unavailable. Please try again later.";
        })
        .finally(() => {
            // Schedule the next fetch operation after 100 milliseconds, whether this operation was successful or not
            setTimeout(fetchImage, 100);
        });
}

// Start the first fetch operation
fetchImage();

function buttonPressed(btn) {
    const altButton = document.getElementById("altButton");
    const longButton = document.getElementById("longButton");

    // If the other button is pressed, unpress it
    if (btn === altButton && longButton.classList.contains('pressed')) {
        longButton.classList.remove('pressed');
    } else if (btn === longButton && altButton.classList.contains('pressed')) {
        altButton.classList.remove('pressed');
    }

    // If this button is already pressed, unpress it; otherwise, press it
    if (btn.classList.contains('pressed')) {
        btn.classList.remove('pressed');
    } else {
        btn.classList.add('pressed');
    }
}

function buttonClicked(btn, code) {
    const button = btn.innerHTML;
    const altButton = document.getElementById("altButton");
    const longButton = document.getElementById("longButton");

    if (altButton.classList.contains('pressed')) {
        code = `ALT_${code}`;
        altButton.classList.remove('pressed');
    } else if (longButton.classList.contains('pressed')) {
        code = `LNG_${code}`;
        longButton.classList.remove('pressed');
    }

    fetch('/key_callback', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ button: code }),
    })
    .then(response => response.json())
    .then(data => console.log(data))
    .catch((error) => {
        console.error('Error:', error);
    });
}
</script>

% include("footer.tpl", title="PiFinder UI")

