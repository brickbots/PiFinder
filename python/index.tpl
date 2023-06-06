<!DOCTYPE html>
<html>
<body>
<img id="image" src="/image" alt="Image served from Bottle server">


    <div id="numpad" style="display: flex; justify-content: space-between;">
        <div style="display: flex; flex-direction: column;">
            <button onclick="buttonClicked(this, 'A')">A</button>
            <button onclick="buttonClicked(this, 'B')">B</button>
            <button onclick="buttonClicked(this, 'C')">C</button>
            <button onclick="buttonClicked(this, 'D')">D</button>
        </div>
        <div style="display: grid; grid-template-columns: repeat(3, 1fr); margin: 0 20px;">
            <button onclick="buttonClicked(this, '1')">1</button>
            <button onclick="buttonClicked(this, '2')">2</button>
            <button onclick="buttonClicked(this, '3')">3</button>
            <button onclick="buttonClicked(this, '4')">4</button>
            <button onclick="buttonClicked(this, '5')">5</button>
            <button onclick="buttonClicked(this, '6')">6</button>
            <button onclick="buttonClicked(this, '7')">7</button>
            <button onclick="buttonClicked(this, '8')">8</button>
            <button onclick="buttonClicked(this, '9')">9</button>
            <button onclick="buttonClicked(this, '0')" style="grid-column: span 3;">0</button>
        </div>
        <div style="display: flex; flex-direction: column;">
            <button onclick="buttonClicked(this, 'UP')">Up</button>
            <button onclick="buttonClicked(this, 'ENT')">Enter</button>
            <button onclick="buttonClicked(this, 'DN')">Down</button>
        </div>
    </div>
    <div style="margin-top: 20px;">
        <button id="altButton" onclick="buttonPressed(this)">Alt</button>
        <button id="longButton" onclick="buttonPressed(this)">Long</button>
    </div>
<script>
        setInterval(function() {
               const imageElement = document.getElementById('image');
               imageElement.src = "/image?t=" + new Date().getTime();
        }, 1000);

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

