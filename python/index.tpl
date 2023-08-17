<!DOCTYPE html>
<html>
<head>
<style>
body {
  background-color: #25383c;
}
.button {
  background-color: #111111;
  color: red;
  border: none;
  border-radius:5px;
  margin: 1px;
}
</style>
<title>PiFinder Remote Control</title>
</head
<body>
    <div id="numpad" style="display: flex; justify-content: space-between;">
        <p id="error"></p>
        <img id="image" src="/image" alt="Image served from Bottle server">


        <div style="display: flex; flex-direction: column; margin: 0px 5px 0px 5px">
            <button class="button" onclick="buttonClicked(this, 'A')">A</button>
            <button class="button" onclick="buttonClicked(this, 'B')">B</button>
            <button class="button" onclick="buttonClicked(this, 'C')">C</button>
            <button class="button" onclick="buttonClicked(this, 'D')">D</button>
            <div style="margin-top: 10px;">
                <button class="button" id="altButton" onclick="buttonPressed(this)">Ent+</button>
                <button class="button" id="longButton" onclick="buttonPressed(this)">Long</button>
            </div>
        </div>
        <div style="display: grid; grid-template-columns: repeat(3, 1fr); margin: 0px 5px 0px 5px">
            <button class="button" onclick="buttonClicked(this, '1')">1</button>
            <button class="button" onclick="buttonClicked(this, '2')">2</button>
            <button class="button" onclick="buttonClicked(this, '3')">3</button>
            <button class="button" onclick="buttonClicked(this, '4')">4</button>
            <button class="button" onclick="buttonClicked(this, '5')">5</button>
            <button class="button" onclick="buttonClicked(this, '6')">6</button>
            <button class="button" onclick="buttonClicked(this, '7')">7</button>
            <button class="button" onclick="buttonClicked(this, '8')">8</button>
            <button class="button" onclick="buttonClicked(this, '9')">9</button>
            <button class="button" onclick="buttonClicked(this, '0')" style="grid-column: span 3;">0</button>
        </div>
        <div style="display: flex; flex-direction: column; margin: 0px 5px 0px 5px">
            <button class="button" onclick="buttonClicked(this, 'UP')">Up</button>
            <button class="button" onclick="buttonClicked(this, 'DN')">Down</button>
            <button class="button" onclick="buttonClicked(this, 'ENT')">Enter</button>
            <button class="button" onclick="gpsLock()">GPSLOCK</button>
        </div>
    </div>
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

        function gpsLock() {
            fetch('/gps-lock', {
                method: 'GET',
            })
            .then(response => response.json())
            .then(data => console.log(data))
            .catch((error) => {
                console.error('Error:', error);
            });
        }

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

            fetch('/callback', {
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

    <style>
        .pressed {
            background-color: #008CBA; /* Blue */
            color: white;
        }
    </style>
</body>
</html>

