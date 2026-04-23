% include("header.tpl", title="PiFinder Logs")
<style>
  .log-container {
    background-color: #1e1e1e;
    color: #d4d4d4;
    font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
    padding: 15px;
    border-radius: 4px;
    height: 600px;
    overflow-y: auto;
    margin-bottom: 20px;
    position: relative;
    -webkit-overflow-scrolling: touch;
  }
  .log-line {
    margin: 0;
    white-space: pre;
    font-size: 13px;
    line-height: 1.4;
    padding: 1px 0;
    min-height: 20px;
    overflow-x: auto;
  }
  .log-content {
    width: max-content;
    min-width: 100%;
  }
  .log-line:hover {
    background-color: rgba(255, 255, 255, 0.05);
  }
  .log-line.error { color: #ff6b6b; }
  .log-line.warning { color: #ffd93d; }
  .log-line.info { color: #6bff6b; }
  .log-line.debug { color: #6b6bff; }
  .loading-message {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    color: #888;
    font-size: 1.2em;
  }
  .controls {
    margin-bottom: 10px;
    display: flex;
    flex-wrap: nowrap;
    gap: 10px;
    align-items: center;
  }
  .controls .btn {
    margin-right: 0;
    white-space: nowrap;
  }
  .controls select {
    height: 36px;
    margin: 0;
    padding: 0 10px;
    width: auto;
    min-width: fit-content;
  }
  .log-stats {
    color: #888;
    font-size: 0.9em;
    margin-bottom: 10px;
  }
  /* Add horizontal scrollbar styles */
  .log-container::-webkit-scrollbar,
  .log-line::-webkit-scrollbar {
    height: 8px;
    width: 8px;
  }
  .log-container::-webkit-scrollbar-track,
  .log-line::-webkit-scrollbar-track {
    background: #2e2e2e;
  }
  .log-container::-webkit-scrollbar-thumb,
  .log-line::-webkit-scrollbar-thumb {
    background: #666;
    border-radius: 4px;
  }
  .log-container::-webkit-scrollbar-thumb:hover,
  .log-line::-webkit-scrollbar-thumb:hover {
    background: #888;
  }
  @media (max-width: 600px) {
    .controls {
      flex-direction: column;
    }
    .controls .btn {
      width: 100%;
      margin-bottom: 5px;
    }
    .log-line {
      font-size: 11px;
    }
  }
</style>

<div class="row valign-wrapper" style="margin: 0px;">
  <div class="col s12">
    <h5 class="grey-text">PiFinder Logs</h5>
  </div>
</div>

<div class="card grey darken-2">
  <div class="card-content">
    <div class="row">
      <div class="col s12">
        <div class="controls">
          <button id="downloadButton" class="btn">
            <i class="material-icons left">download</i>Download All Logs
          </button>
          <button id="pauseButton" class="btn">
            <i class="material-icons left">pause</i>Pause
          </button>
          <button id="restartFromCurrent" class="btn" style="display: none;">
            <i class="material-icons left">play_arrow</i>Resume from Current
          </button>
          <button id="restartFromEnd" class="btn" style="display: none;">
            <i class="material-icons left">replay</i>Restart from End
          </button>
          <button id="copyButton" class="btn">
            <i class="material-icons left">content_copy</i>Copy to Clipboard
          </button>
          <button id="uploadLogConfButton" class="btn" onclick="document.getElementById('uploadLogConfInput').click()">
            <i class="material-icons left">upload_file</i>Upload Log Conf
          </button>
          <input type="file" id="uploadLogConfInput" accept=".json" style="display:none">
          <select id="configSelect" class="browser-default">
            <option value="" disabled selected>Select Log Configuration</option>
          </select>
        </div>
        <div class="log-stats">
          Total lines: <span id="totalLines">0</span>
        </div>
      </div>
    </div>

    <div class="row">
      <div class="col s12">
        <div class="log-container" id="logViewer">
          <div id="loadingMessage" class="loading-message">Loading log files...</div>
          <div id="logContent" class="log-content"></div>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
let currentPosition = 0;
let isPaused = false;
let logBuffer = [];
const BUFFER_SIZE = 100;
const LINE_HEIGHT = 20;
let updateInterval;
let lastLine = '';

// Backoff state for when the log file is not yet available.
// This page intentionally does NOT fetch the home route, so iwgetid is never triggered here.
const MIN_POLL_INTERVAL = 1000;
const MAX_POLL_INTERVAL = 10000;
let currentPollInterval = MIN_POLL_INTERVAL;

function scheduleFetch() {
    clearInterval(updateInterval);
    updateInterval = setInterval(fetchLogs, currentPollInterval);
}

function fetchLogs() {
    if (isPaused) return;

    fetch(`/logs/stream?position=${currentPosition}`)
        .then(response => response.json())
        .then(data => {
            if (data.file_not_found) {
                // Back off exponentially up to MAX_POLL_INTERVAL
                currentPollInterval = Math.min(currentPollInterval * 2, MAX_POLL_INTERVAL);
                scheduleFetch();
                return;
            }

            // Reset backoff on a successful response
            if (currentPollInterval !== MIN_POLL_INTERVAL) {
                currentPollInterval = MIN_POLL_INTERVAL;
                scheduleFetch();
            }

            if (!data.logs || data.logs.length === 0) return;

            currentPosition = data.position;
            const logContent = document.getElementById('logContent');

            // Add new logs to buffer, skipping duplicates
            data.logs.forEach(line => {
                if (line !== lastLine) {
                    logBuffer.push(line);
                    lastLine = line;
                }
            });

            // Trim buffer if it exceeds size
            if (logBuffer.length > BUFFER_SIZE) {
                logBuffer = logBuffer.slice(-BUFFER_SIZE);
            }

            // Update display
            updateLogDisplay();
        })
        .catch(error => console.error('Error fetching logs:', error));
}

function updateLogDisplay() {
    const logContent = document.getElementById('logContent');
    logContent.innerHTML = '';
    
    logBuffer.forEach(line => {
        const logLine = document.createElement('div');
        logLine.style.height = `${LINE_HEIGHT}px`;
        logLine.style.whiteSpace = 'pre';
        logLine.textContent = line;
        
        // Add color based on log level
        if (line.includes('ERROR')) {
            logLine.style.color = '#ff6b6b';
        } else if (line.includes('WARNING')) {
            logLine.style.color = '#ffd93d';
        } else if (line.includes('INFO')) {
            logLine.style.color = '#6bff6b';
        } else if (line.includes('DEBUG')) {
            logLine.style.color = '#6b6bff';
        }
        
        logContent.appendChild(logLine);
    });
    
    // Auto-scroll if not paused
    if (!isPaused) {
        logContent.scrollTop = logContent.scrollHeight;
    }
}

function togglePause() {
    isPaused = !isPaused;
    const pauseButton = document.getElementById('pauseButton');
    pauseButton.textContent = isPaused ? 'Resume' : 'Pause';
    
    if (!isPaused) {
        // Resume fetching from last position
        fetchLogs();
    }
}

function restartFromEnd() {
    currentPosition = 0;
    logBuffer = [];
    isPaused = false;
    currentPollInterval = MIN_POLL_INTERVAL;
    document.getElementById('pauseButton').textContent = 'Pause';
    fetchLogs();
    scheduleFetch();
}

// Start fetching logs when page loads
document.addEventListener('DOMContentLoaded', () => {
    // Show loading message
    const loadingMessage = document.querySelector('.loading-message');
    loadingMessage.style.display = 'flex';
    
    // Start log fetching
    fetchLogs();
    scheduleFetch();
    
    // Hide loading message after first logs appear
    const observer = new MutationObserver((mutations) => {
        if (document.getElementById('logContent').textContent.trim()) {
            loadingMessage.style.display = 'none';
            observer.disconnect();
        }
    });
    
    observer.observe(document.getElementById('logContent'), {
        childList: true,
        subtree: true,
        characterData: true
    });

    // Load component levels
    updateComponentLevels();
});

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    clearInterval(updateInterval);
});

// Add copy to clipboard functionality
document.getElementById('copyButton').addEventListener('click', function() {
    const logContent = document.getElementById('logContent');
    const text = logContent.innerText;
    
    navigator.clipboard.writeText(text).then(() => {
        // Visual feedback
        const originalText = this.innerHTML;
        this.innerHTML = '<i class="material-icons left">check</i>Copied!';
        setTimeout(() => {
            this.innerHTML = originalText;
        }, 2000);
    }).catch(err => {
        console.error('Failed to copy text: ', err);
        // Visual feedback for error
        const originalText = this.innerHTML;
        this.innerHTML = '<i class="material-icons left">error</i>Failed to copy';
        setTimeout(() => {
            this.innerHTML = originalText;
        }, 2000);
    });
});

// Log configuration management
function loadLogConfigs() {
    fetch('/logs/configs')
        .then(response => response.json())
        .then(data => {
            const configSelect = document.getElementById('configSelect');
            configSelect.innerHTML = '<option value="" disabled>Select Log Configuration</option>';
            data.configs.forEach(cfg => {
                const option = document.createElement('option');
                option.value = cfg.file;
                option.textContent = cfg.name;
                if (cfg.active) option.selected = true;
                configSelect.appendChild(option);
            });
        })
        .catch(error => console.error('Error fetching log configs:', error));
}

document.getElementById('configSelect').addEventListener('change', function(e) {
    const configFile = e.target.value;
    if (!configFile) return;
    if (!confirm(`Switch log configuration to "${e.target.options[e.target.selectedIndex].text}" and restart PiFinder?`)) {
        loadLogConfigs(); // reset selection
        return;
    }
    // Use a real form POST so the browser navigates to the restart page HTML
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = '/logs/switch_config';
    const input = document.createElement('input');
    input.type = 'hidden';
    input.name = 'logconf_file';
    input.value = configFile;
    form.appendChild(input);
    document.body.appendChild(form);
    form.submit();
});

document.getElementById('uploadLogConfInput').addEventListener('change', function(e) {
    const file = e.target.files[0];
    if (!file) return;
    if (!file.name.startsWith('logconf_') || !file.name.endsWith('.json')) {
        alert('File must be named logconf_<name>.json');
        e.target.value = '';
        return;
    }
    const formData = new FormData();
    formData.append('config_file', file);
    fetch('/logs/upload_config', { method: 'POST', body: formData })
        .then(response => response.json())
        .then(result => {
            if (result.status === 'ok') {
                loadLogConfigs();
            } else {
                alert('Upload failed: ' + result.message);
            }
        })
        .catch(error => console.error('Error uploading log config:', error));
    e.target.value = '';
});

// Initial load of configs
loadLogConfigs();

// Set up button event listeners
document.getElementById('pauseButton').addEventListener('click', function() {
    if (isPaused) {
        togglePause();
    } else {
        togglePause();
    }
});

document.getElementById('restartFromCurrent').addEventListener('click', function() {
    togglePause();
});

document.getElementById('restartFromEnd').addEventListener('click', function() {
    restartFromEnd();
});
</script>

% include("footer.tpl") 