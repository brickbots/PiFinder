% include("header.tpl", title="PiFinder UI")

<div id="error" class="error-message"></div>
<img id="image" src="" alt="PiFinder Screen" class="pifinder-screen">

<div class="status-items">
    <div class="item">
        <div class="key">Software Version</div><div class="value">{{software_version}}</div>
    </div>
    <div class="item">
        <div class="key">WiFi Mode</div><div class="value">{{wifi_mode}}</div>
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
            setTimeout(fetchImage, 500);
        });
}

// Start the first fetch operation
fetchImage();

</script>

% include("footer.tpl", title="PiFinder UI")

